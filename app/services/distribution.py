"""Immutable manifests and content-addressed files in the persistent data volume."""
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import stat
import zipfile
import zlib
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select, update
from app.core.config import settings
from app.models import AssetPackage, AssetVersion, Device, FirmwareRelease, QuizCatalog, QuizQuestion

KINDS = {"communication": "Kommunikation", "avatar": "Avatare", "common": "Common", "sound": "Sounds", "weather": "Wetter", "game": "Spiele", "quiz": "Quiz", "chill": "Chill"}
EVENT_LABELS = {"offered": "Update angeboten", "download_started": "Download begonnen",
    "asset_installed": "Asset installiert", "firmware_installed": "Firmware installiert",
    "boot_success": "Neustart erfolgreich", "firmware_confirmed": "Neue Firmware bestätigt",
    "sync_success": "Sync erfolgreich", "update_failed": "Update fehlgeschlagen",
    "checksum_failed": "Prüfsumme falsch", "download_aborted": "Download abgebrochen", "rollback": "Rollback durchgeführt"}
BUILTINS = {"dragon": "Drachi", "jellyfish": "Qualle", "walrus": "Walross", "frog": "Frosch", "redpanda": "Roter Panda"}


def blob_path(digest):
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise HTTPException(404)
    return settings.data_dir / "distribution" / "blobs" / digest[:2] / digest


def store_bytes(data):
    digest = hashlib.sha256(data).hexdigest()
    path = blob_path(digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Each writer has its own temporary file. The final address is immutable.
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as out:
        temp = Path(out.name)
        out.write(data)
        out.flush()
        os.fsync(out.fileno())
    os.replace(temp, path)
    return {"sha256": digest, "size": len(data)}


async def store_upload(upload, limit):
    root = settings.data_dir / "distribution" / "staging"
    root.mkdir(parents=True, exist_ok=True)
    temp = root / str(uuid4())
    digest = hashlib.sha256()
    size = 0
    try:
        with temp.open("xb") as out:
            while chunk := await upload.read(65536):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, "Datei zu groß")
                digest.update(chunk)
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        if not size:
            raise HTTPException(422, "Leere Datei")
        target = blob_path(digest.hexdigest())
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temp, target)
        return {"sha256": digest.hexdigest(), "size": size}
    finally:
        temp.unlink(missing_ok=True)
        await upload.close()


def safe_name(name):
    if (not name or len(name) > 180 or name.startswith("/") or "\\" in name
            or any(part in {"", ".", ".."} for part in name.split("/"))
            or not re.fullmatch(r"[a-zA-Z0-9_. /-]+", name)):
        raise HTTPException(422, "Ungültiger relativer Dateipfad")
    if name in {"definition.json", "manifest.json"}:
        raise HTTPException(422, "Dieser Dateiname wird vom Server erzeugt")
    return name


ASSET_FILE_LIMIT = 16 * 1024 * 1024
ASSET_UPLOAD_LIMIT = 64 * 1024 * 1024
ASSET_UPLOAD_FILES = 1000


def unpack_asset_zip(path, folder="", metadata=None):
    """Import individual blobs; never extract archive-controlled paths onto disk."""
    prefix = folder.rstrip("/") + "/" if folder else ""
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > ASSET_UPLOAD_FILES:
                raise HTTPException(413, "ZIP enthält zu viele Einträge (maximal 1000)")
            names, members, total = set(), [], 0
            for entry in entries:
                raw = entry.filename
                if entry.orig_filename != raw:
                    raise HTTPException(422, "Ungültiger ZIP-Dateipfad")
                # A Chill manifest describes sprites; it is not the immutable sync manifest.
                is_manifest = metadata is not None and not folder and raw == "manifest.json"
                # Bundles may contain an old generated definition. Never import it
                # over the definition published from the current package metadata.
                is_definition = not folder and raw == "definition.json"
                name = raw if is_manifest or is_definition else safe_name(prefix + (raw[:-1] if entry.is_dir() else raw))
                mode = stat.S_IFMT(entry.external_attr >> 16)
                allowed = {0, stat.S_IFDIR} if entry.is_dir() else {0, stat.S_IFREG}
                if mode not in allowed or entry.flag_bits & 1:
                    raise HTTPException(422, "ZIP darf keine Links, Spezialdateien oder verschlüsselten Einträge enthalten")
                if name in names:
                    raise HTTPException(422, "ZIP enthält doppelte Pfade")
                names.add(name)
                if entry.is_dir():
                    continue
                total += entry.file_size
                if entry.file_size > ASSET_FILE_LIMIT or total > ASSET_UPLOAD_LIMIT:
                    raise HTTPException(413, "Entpacktes ZIP überschreitet das Größenlimit")
                members.append((name, entry))
            if not members:
                raise HTTPException(422, "ZIP enthält keine Dateien")
            file_names = {name for name, _ in members}
            if any(str(parent) in file_names for name in names for parent in PurePosixPath(name).parents):
                raise HTTPException(422, "ZIP verwendet einen Pfad zugleich als Datei und Ordner")
            result = {}
            for name, entry in members:
                with archive.open(entry) as stream:
                    data = stream.read(ASSET_FILE_LIMIT + 1)
                if len(data) > ASSET_FILE_LIMIT:
                    raise HTTPException(413, "Entpackte Datei ist zu groß")
                if len(data) != entry.file_size:
                    raise HTTPException(422, "Unvollständige ZIP-Datei")
                if name == "definition.json":
                    continue
                if name == "manifest.json" and metadata is not None:
                    try:
                        source = json.loads(data)
                        if not isinstance(source, dict) or source.get("type") != "chill":
                            raise ValueError()
                        metadata.update(normalize_chill(source))
                    except (ValueError, TypeError, KeyError, IndexError):
                        raise HTTPException(422, "Ungültiges Chill-Manifest")
                elif name != "README.txt" or metadata is None:
                    result[name] = store_bytes(data)
            if not result and not metadata:
                raise HTTPException(422, "ZIP enthält keine importierbaren Dateien")
            return result
    except (zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError, RuntimeError, EOFError, zlib.error):
        raise HTTPException(422, "ZIP ist beschädigt oder verwendet eine nicht unterstützte Komprimierung")


def current(db, package):
    return db.scalar(select(AssetVersion).where(AssetVersion.package_id == package.id, AssetVersion.version == package.current_version))


PET_STATES = {"idle", "happy", "sad", "hungry", "tired", "dirty", "eating", "playing", "sleeping"}


def discover_pet(files):
    """Keep archive paths intact, including optional outer folders."""
    animations, backgrounds = {}, {}
    for path in sorted(files):
        parts = PurePosixPath(path).parts
        if not path.lower().endswith(".png"):
            continue
        if len(parts) >= 2 and parts[-2].lower() in PET_STATES:
            animations.setdefault(parts[-2].lower(), {"frames": [], "frameDurationMs": 400})["frames"].append(path)
        for period in ("day", "night"):
            if PurePosixPath(path).stem.lower() == f"background_{period}" or (len(parts) >= 2 and parts[-2].lower() == f"background_{period}"):
                backgrounds.setdefault(period, path)
    return {"animations": animations, "backgrounds": backgrounds}


def with_pet_metadata(files, metadata):
    """Enrich legacy uploads, retaining explicit pet and sidebar definitions."""
    metadata = copy.deepcopy(metadata)
    discovered = discover_pet(files)
    root_animations = metadata.get("animations", {})
    root_pet = {name: animation for name, animation in root_animations.items()
                if name in PET_STATES and isinstance(animation, dict)
                and (name != "idle" or len(animation.get("frames", [])) > 1)
                and any(isinstance(p, str) and p.lower().endswith(".png") and p in files
                        for p in animation.get("frames", []))}
    if not (discovered["animations"] or discovered["backgrounds"] or root_pet or "tamagotchi" in metadata):
        return metadata
    pet = metadata.setdefault("tamagotchi", {})
    if not isinstance(pet, dict):
        raise HTTPException(422, "tamagotchi muss ein Objekt sein")
    animations = pet.setdefault("animations", {})
    backgrounds = pet.setdefault("backgrounds", {})
    if not isinstance(animations, dict) or not isinstance(backgrounds, dict):
        raise HTTPException(422, "Tamagotchi animations/backgrounds müssen Objekte sein")
    for name, animation in discovered["animations"].items():
        animations.setdefault(name, animation)
    for name, animation in root_pet.items():
        # Generic animation paths are also supported, even without state folders.
        frames = [p for p in animation.get("frames", []) if isinstance(p, str) and p.lower().endswith(".png") and p in files]
        if frames:
            animations.setdefault(name, {**animation, "frames": frames})
    for period, path in discovered["backgrounds"].items():
        backgrounds.setdefault(period, path)
    if "idle" not in root_animations and "idle" in animations and not any(p.startswith("animations/idle/") for p in files):
        metadata["animations"] = {**root_animations, "idle": copy.deepcopy(animations["idle"])}
    return metadata


def validate_animations(animations, files):
    if not isinstance(animations, dict):
        raise HTTPException(422, "animations muss ein Objekt sein")
    for animation in animations.values():
        if not isinstance(animation, dict) or not isinstance(animation.get("frames"), list) or not animation["frames"]:
            raise HTTPException(422, "Animationen benötigen eine nicht leere frames-Liste")
        if any(not isinstance(frame, str) or frame not in files for frame in animation["frames"]):
            raise HTTPException(422, "Animationsframe fehlt im Paket")
        timing = animation.get("frameDurationMs", 100)
        if isinstance(timing, bool) or not isinstance(timing, int) or timing < 1:
            raise HTTPException(422, "frameDurationMs muss positiv sein")


def normalize_chill(source):
    metadata = copy.deepcopy(source)
    if not isinstance(source.get("slider"), dict) or not isinstance(source.get("sprites"), list):
        raise ValueError()
    for key in ("id", "type", "title", "name", "version"):
        metadata.pop(key, None)
    metadata.setdefault("scene", {"flight_speed": "space", "fire_intensity": "fire", "snowfall_intensity": "snow"}.get(source.get("slider", {}).get("meaning")))
    layout = {"snow": [(40, 40), (270, 66), (190, 58), (0, 94), (362, 12)], "fire": [(174, 100), (178, 100), (178, 12)]}.get(metadata["scene"], [])
    for index, sprite in enumerate(metadata.get("sprites", [])):
        if not isinstance(sprite, dict):
            raise ValueError()
        if index < len(layout):
            sprite.setdefault("x", layout[index][0])
            sprite.setdefault("y", layout[index][1])
        if "pattern" in sprite:
            count = sprite.get("frames")
            if type(count) is not int or not 1 <= count <= 8:
                raise ValueError()
            sprite["frames"] = [sprite["pattern"] % i for i in range(count)]
            sprite.pop("pattern", None)
            sprite.setdefault("frameDurationMs", 200)
    metadata.setdefault("preview", next((s.get("file") or s.get("frames", [None])[0] for s in metadata.get("sprites", [])), None))
    metadata.setdefault("minFirmware", "1.0.0-beta.18")
    return metadata


def validate_chill(metadata, files):
    # Empty legacy packages can still be populated through the existing asset editor.
    if "scene" not in metadata:
        return
    if not isinstance(metadata["scene"], str) or metadata["scene"] not in {"space", "fire", "snow"}:
        raise HTTPException(422, "Unbekannte Chill-Szene")
    slider = metadata.get("slider", {})
    if not isinstance(slider, dict) or slider.get("min") != 0 or slider.get("max") != 100 or type(slider.get("default")) is not int or not 0 <= slider["default"] <= 100:
        raise HTTPException(422, "Chill-Slider benötigt 0–100 und einen gültigen Standardwert")
    sprites = metadata.get("sprites")
    if not isinstance(sprites, list) or not 1 <= len(sprites) <= 16:
        raise HTTPException(422, "Chill benötigt 1–16 Sprites")
    total_frames = 0
    for sprite in sprites:
        if not isinstance(sprite, dict):
            raise HTTPException(422, "Ungültiger Chill-Sprite")
        if ("file" in sprite) == ("frames" in sprite):
            raise HTTPException(422, "Chill-Sprite benötigt entweder file oder frames")
        for coordinate, limit in (("x", 428), ("y", 142)):
            if coordinate in sprite and (type(sprite[coordinate]) is not int or not -142 <= sprite[coordinate] <= limit):
                raise HTTPException(422, "Ungültige Chill-Sprite-Position")
        size = sprite.get("size", [])
        paths = sprite.get("frames", [sprite.get("file")])
        if (not isinstance(size, list) or len(size) != 2 or any(type(n) is not int or not 1 <= n <= 142 for n in size)
                or not isinstance(paths, list) or not 1 <= len(paths) <= 8
                or any(not isinstance(p, str) or not p.endswith(".png") or p not in files for p in paths)):
            raise HTTPException(422, "Chill-Sprite oder Animationsframe fehlt / überschreitet das Limit")
        total_frames += len(paths)
    if total_frames > 32:
        raise HTTPException(422, "Chill erlaubt höchstens 32 Sprite-Frames insgesamt")
    if metadata["scene"] == "fire" and not any(s.get("role") == "animation" and s.get("frames") for s in sprites):
        raise HTTPException(422, "Lagerfeuer benötigt Flammenframes")


def publish(db, package, files, metadata, expected):
    if package.current_version != expected:
        raise HTTPException(409, "Paket wurde inzwischen geändert. Bitte neu laden.")
    if not isinstance(metadata, dict):
        raise HTTPException(422, "Definition muss ein JSON-Objekt sein")
    metadata = dict(metadata)
    if package.kind == "chill":
        validate_chill(metadata, files)
    minimum = metadata.get("minFirmware")
    if minimum is not None:
        version_key(minimum)
    animations = metadata.get("animations", {})
    validate_animations(animations, files)
    if package.kind == "avatar":
        metadata = with_pet_metadata(files, metadata)
        animations = metadata.get("animations", {})
        pet = metadata.get("tamagotchi", {})
        pet_animations = pet.get("animations", {})
        validate_animations(pet_animations, files)
        if any(not frame.lower().endswith(".png") for a in pet_animations.values() for frame in a["frames"]):
            raise HTTPException(422, "Tamagotchi-Frames müssen PNG sein")
        for period, path in pet.get("backgrounds", {}).items():
            if period not in {"day", "night"} or not isinstance(path, str) or not path.lower().endswith(".png") or path not in files:
                raise HTTPException(422, "Ungültiger Tamagotchi-Hintergrund")
    # A folder animations/<name>/ automatically becomes an animation.
    if package.kind == "avatar":
        animations = dict(animations)
        for path in sorted(files):
            parts = PurePosixPath(path).parts
            if len(parts) >= 3 and parts[0] == "animations" and parts[1] not in metadata.get("animations", {}):
                animations.setdefault(parts[1], {"frames": [], "frameDurationMs": 100})["frames"].append(path)
        metadata["animations"] = animations
    preview = metadata.get("preview")
    if preview and (not isinstance(preview, str) or preview not in files):
        raise HTTPException(422, "Vorschaudatei fehlt im Paket")
    version = expected + 1
    definition = {**metadata, "id": package.id, "name": package.name, "type": package.kind, "version": version}
    files = {name: info for name, info in files.items() if name != "definition.json"}
    files["definition.json"] = store_bytes(json.dumps(definition, ensure_ascii=False, sort_keys=True).encode())
    manifest = {"schemaVersion": 1, "packageId": package.id, "type": package.kind, "version": version,
                "definition": definition, "files": [{"path": name, **info,
                "url": f"/api/v1/packages/{package.id}/versions/{version}/files/{name}"} for name, info in sorted(files.items())]}
    result = db.execute(update(AssetPackage).where(AssetPackage.id == package.id, AssetPackage.current_version == expected)
                        .values(current_version=version).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        raise HTTPException(409, "Gleichzeitige Änderung. Bitte neu laden.")
    db.add(AssetVersion(package_id=package.id, version=version, manifest=manifest))
    db.flush()
    db.refresh(package)
    return manifest


def file_map(version):
    return {f["path"]: {"sha256": f["sha256"], "size": f["size"]} for f in version.manifest["files"] if f["path"] != "definition.json"} if version else {}


def editable_definition(version):
    return {k: copy.deepcopy(v) for k, v in version.manifest["definition"].items() if k not in {"id", "name", "type", "version"}} if version else {}


class Question(BaseModel):
    q: str = Field(min_length=1, max_length=10000)
    a: list[str] = Field(min_length=4, max_length=4)
    explanation: str = Field(default="", max_length=10000)
    minAge: int = Field(default=0, ge=0, le=120)
    difficulty: int = Field(default=1, ge=1, le=10)
    tags: list[str] = Field(default_factory=list, max_length=100)


def parse_questions(raw):
    try:
        data = json.loads(raw)
        rows = data if isinstance(data, list) else data["questions"]
        if not isinstance(rows, list) or len(rows) > 10000:
            raise ValueError()
        return [Question.model_validate(row).model_dump() for row in rows]
    except (ValueError, TypeError, KeyError, ValidationError):
        raise HTTPException(422, "Ungültige Quiz-Daten: pro Frage q und vier Antworten a angeben")


def quiz_data(catalog):
    return [{"q": q.question, "a": q.answers, "explanation": q.explanation, "minAge": q.min_age,
             "difficulty": q.difficulty, "tags": q.tags} for q in catalog.questions]


def publish_quiz(db, package, catalog, expected):
    files = {"questions.json": store_bytes(json.dumps({"questions": quiz_data(catalog)}, ensure_ascii=False).encode())}
    return publish(db, package, files, {"questionsFile": "questions.json", "questionCount": len(catalog.questions)}, expected)


def catalog_package_id(db, catalog):
    base = f"quiz-{catalog.id}"
    candidate = base
    suffix = 1
    while db.get(AssetPackage, candidate):
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def ensure_packages(db):
    """Idempotent adoption: original catalogs, question IDs and device links survive."""
    from app.services.communication import ensure_package
    changed = ensure_package(db)
    for path in sorted((Path(__file__).resolve().parents[1] / "defaults" / "chill").glob("*.zip")):
        key = path.name.removesuffix("-v1.zip")
        if not db.get(AssetPackage, key):
            with zipfile.ZipFile(path) as archive:
                name = json.loads(archive.read("manifest.json"))["name"]
            metadata = {}
            files = unpack_asset_zip(path, metadata=metadata)
            package = AssetPackage(id=key, kind="chill", name=name, current_version=0)
            db.add(package); db.flush()
            publish(db, package, files, metadata, 0)
            changed = True
    for catalog in db.scalars(select(QuizCatalog)).all():
        if not db.scalar(select(AssetPackage).where(AssetPackage.catalog_id == catalog.id)):
            package = AssetPackage(id=catalog_package_id(db, catalog), kind="quiz", name=catalog.name, catalog_id=catalog.id, current_version=0)
            db.add(package); db.flush()
            publish_quiz(db, package, catalog, 0)
            changed = True
    for key, label in BUILTINS.items():
        package = db.get(AssetPackage, "avatar-" + key)
        svg = (Path("app/static/avatars") / f"{key}.svg").read_bytes()
        original_files = {"preview.svg": {"sha256": hashlib.sha256(svg).hexdigest(), "size": len(svg)}}
        original_definition = {"preview": "preview.svg", "format": "svg", "animations": {}}
        if not package:
            package = AssetPackage(id="avatar-" + key, kind="avatar", name=label, current_version=0)
            db.add(package); db.flush()
        version = current(db, package)
        # Upgrade only the exact original built-in. Never replace uploaded/custom avatars.
        original = (package.kind == "avatar" and package.current_version == 1
                    and file_map(version) == original_files
                    and editable_definition(version) == original_definition)
        if package.current_version == 0 or original:
            png = (Path("app/static/avatars") / f"{key}.png").read_bytes()
            publish(db, package, {"preview.svg": store_bytes(svg), "preview.png": store_bytes(png)},
                    {"preview": "preview.png", "format": "png", "animations": {
                        "idle": {"frames": ["preview.png"], "frameDurationMs": 1000}}}, package.current_version)
            changed = True
    # Existing uploads predate pet metadata. Publish a new immutable version once;
    # unchanged files keep their hashes and are reused by the regular device sync.
    for package in db.scalars(select(AssetPackage).where(AssetPackage.kind == "avatar")).all():
        version = current(db, package)
        if not version:
            continue
        files = file_map(version)
        metadata = editable_definition(version)
        enriched = with_pet_metadata(files, metadata)
        if enriched != metadata:
            publish(db, package, files, enriched, package.current_version)
            changed = True
    if changed:
        db.commit()


def desired_packages(db, device):
    avatar = device.avatar if device.avatar.startswith("avatar-") else "avatar-" + device.avatar
    from app.services.communication import PACKAGE_ID
    ids = {avatar, *(device.content_selection or [])}
    ids.discard(PACKAGE_ID)
    if device.communication_enabled:
        ids.add(PACKAGE_ID)
    catalogs = {c.id for c in device.quiz_catalogs if c.enabled}
    packages = db.scalars(select(AssetPackage).order_by(AssetPackage.id)).all()
    desired = [p for p in packages if p.id in ids or p.kind == "common" or p.catalog_id in catalogs]
    # Deterministic adoption of legacy multi-scene selections without a new DB field.
    chill = next((p.id for p in desired if p.kind == "chill"), None)
    return [p for p in desired if p.kind != "chill" or p.id == chill]


def version_key(version):
    # A deliberately small SemVer subset suitable for firmware release names.
    match = re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-beta\.(0|[1-9][0-9]*))?", str(version))
    if not match or len(str(version)) > 40:
        raise HTTPException(422, "Version muss X.Y.Z oder X.Y.Z-beta.N sein")
    major, minor, patch, beta = match.groups()
    return (int(major), int(minor), int(patch), beta is None, int(beta or 0))


def firmware_target(db, device):
    releases = db.scalars(select(FirmwareRelease)).all()
    releases = [r for r in releases if device.firmware_channel == "beta" or r.channel == "stable"]
    return max(releases, key=lambda r: version_key(r.version), default=None)


def firmware_offer(db, device, installed):
    release = firmware_target(db, device)
    if not release or release.version == installed:
        return None
    try:
        if installed and version_key(release.version) <= version_key(installed):
            return None
    except HTTPException:
        # Unknown legacy version: require an explicit valid report before automatic OTA.
        return None
    return {"id": release.id, "version": release.version, "channel": release.channel,
            "size": release.size, "sha256": release.sha256, "url": f"/api/v1/firmware/{release.id}/binary"}


def device_context(db, device):
    from app.models import SyncRun, SyncEvent
    packages = db.scalars(select(AssetPackage).order_by(AssetPackage.name)).all()
    desired = desired_packages(db, device)
    runs = db.scalars(select(SyncRun).where(SyncRun.device_id == device.id).order_by(SyncRun.created_at.desc()).limit(20)).all()
    events = db.scalars(select(SyncEvent).where(SyncEvent.run_id.in_([r.id for r in runs])).order_by(SyncEvent.id.desc()).limit(100)).all() if runs else []
    avatar_id = device.avatar if device.avatar.startswith("avatar-") else "avatar-" + device.avatar
    avatar = db.get(AssetPackage, avatar_id)
    preview = None
    pet_preview = {"animations": {}, "backgrounds": {}}
    if avatar and (v := current(db, avatar)):
        definition = v.manifest["definition"]
        pet = definition.get("tamagotchi", {})
        animations = dict(pet.get("animations", {}))
        if "idle" not in animations:
            idle = definition.get("animations", {}).get("idle", {})
            frames = [p for p in idle.get("frames", []) if p.lower().endswith(".png")]
            if not frames and str(definition.get("preview", "")).lower().endswith(".png"):
                frames = [definition["preview"]]
            if frames:
                animations["idle"] = {**idle, "frames": frames}
        urls = {f["path"]: f["url"] for f in v.manifest["files"]}
        pet_preview = {"backgrounds": {k: urls.get(p) for k, p in pet.get("backgrounds", {}).items()},
                       "animations": {k: {**a, "frames": [urls[p] for p in a["frames"] if p in urls]}
                                      for k, a in animations.items()}}
        path = v.manifest["definition"].get("preview")
        preview = next((f["url"] for f in v.manifest["files"] if f["path"] == path), None)
        if not preview:
            preview = next((f["url"] for f in v.manifest["files"] if f["path"].lower().endswith((".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif"))), None)
    chill = []
    for package in desired:
        if package.kind == "chill":
            v = current(db, package)
            if not v:
                continue
            definition = v.manifest["definition"]
            path = definition.get("preview")
            urls = {f["path"]: f["url"] for f in v.manifest["files"]}
            chill.append({"name": package.name, "scene": definition.get("scene"), "slider": definition.get("slider", {}).get("default", 45),
                          "sprites": [{**s, "url": urls.get(s.get("file") or s.get("frames", [None])[0])} for s in definition.get("sprites", [])],
                          "preview": urls.get(path)})
    return {"sync_labels": EVENT_LABELS, "firmware_pending": firmware_offer(db, device, device.firmware_version), "preview_chill": chill, "asset_packages": packages, "desired_packages": desired, "firmware_target": firmware_target(db, device),
            "sync_runs": runs, "sync_events": events, "asset_avatar_preview": preview, "pet_preview": pet_preview,
            "pending_assets": [p for p in desired if device.installed_assets.get(p.id) != p.current_version], "asset_kinds": KINDS}
