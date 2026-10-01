import json
import re
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from starlette.concurrency import run_in_threadpool
from pathlib import PurePosixPath
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models import AssetPackage, AssetVersion, Device, FirmwareRelease, QuizCatalog, QuizQuestion
from app.services import distribution as service
from app.web.routes import templates, redir

router = APIRouter()


def package_or_404(db, package_id):
    package = db.get(AssetPackage, package_id)
    if not package:
        raise HTTPException(404)
    return package

@router.get("/assets")
def assets(request: Request, kind: str = "", db: Session = Depends(get_db)):
    service.ensure_packages(db)
    query = select(AssetPackage, AssetVersion.manifest).outerjoin(AssetVersion,
        (AssetVersion.package_id == AssetPackage.id) & (AssetVersion.version == AssetPackage.current_version)
    ).order_by(AssetPackage.kind, AssetPackage.name)
    if kind:
        query = query.where(AssetPackage.kind == kind)
    rows = db.execute(query).all()
    package_stats = {}
    for package, manifest in rows:
        files = manifest["files"] if manifest else []
        package_stats[package.id] = {"file_count": len(files), "size": sum(file["size"] for file in files)}
    return templates.TemplateResponse(request, "assets.html", {
        "packages": [package for package, _ in rows], "package_stats": package_stats, "kinds": service.KINDS, "kind": kind})

@router.post("/assets")
def create_package(package_id: str = Form(), name: str = Form(), kind: str = Form(), db: Session = Depends(get_db)):
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", package_id) or len(package_id) > 100 or kind not in service.KINDS or not name.strip() or len(name) > 120:
        raise HTTPException(422, "Gültige Paket-ID, Name und Kategorie angeben")
    if kind == "communication" or package_id == "communication-messages":
        raise HTTPException(422, "Das gemeinsame Paket wird unter Kommunikation verwaltet")
    if kind == "avatar" and not package_id.startswith("avatar-"):
        raise HTTPException(422, "Avatar-Paket-IDs beginnen mit avatar-")
    if db.get(AssetPackage, package_id):
        raise HTTPException(409, "Paket-ID bereits vorhanden")
    package = AssetPackage(id=package_id, name=name.strip(), kind=kind, current_version=0)
    db.add(package)
    if kind == "quiz":
        catalog = QuizCatalog(name=package.name)
        db.add(catalog); db.flush()
        package.catalog_id = catalog.id
        db.flush()
        service.publish_quiz(db, package, catalog, 0)
    else:
        db.flush()
        service.publish(db, package, {}, {}, 0)
    db.commit()
    return redir(f"/assets/{package.id}")

@router.get("/assets/{package_id}")
def edit_package(package_id: str, request: Request, version: int | None = None, db: Session = Depends(get_db)):
    service.ensure_packages(db)
    package = package_or_404(db, package_id)
    versions = db.scalars(select(AssetVersion).where(AssetVersion.package_id == package.id).order_by(AssetVersion.version.desc())).all()
    selected = next((v for v in versions if v.version == (version or package.current_version)), None)
    if not selected:
        raise HTTPException(404)
    catalog = db.get(QuizCatalog, package.catalog_id) if package.catalog_id else None
    return templates.TemplateResponse(request, "asset_edit.html", {"package": package, "versions": versions, "selected": selected,
        "definition": json.dumps(service.editable_definition(selected), ensure_ascii=False, indent=2),
        "quiz_json": json.dumps({"questions": service.quiz_data(catalog)}, ensure_ascii=False, indent=2) if catalog else None,
        "catalog": catalog, "kinds": service.KINDS})

@router.post("/assets/{package_id}/files")
async def upload_files(package_id: str, files: list[UploadFile] = File(), folder: str = Form(""), expected: int = Form(), db: Session = Depends(get_db)):
    package = package_or_404(db, package_id)
    if package.kind in {"quiz", "communication"}:
        raise HTTPException(422, "Generierte Inhalte über den jeweiligen Inhaltseditor bearbeiten")
    previous = service.current(db, package)
    mapping = service.file_map(previous)
    if len(files) > 200:
        raise HTTPException(413, "Maximal 200 Dateien pro Upload")
    if package.current_version != expected:
        raise HTTPException(409, "Paket wurde inzwischen geändert. Bitte neu laden.")
    incoming = {}
    for upload in files:
        name = service.safe_name((folder.rstrip("/") + "/" if folder else "") + (upload.filename or ""))
        is_zip = (upload.filename or "").lower().endswith(".zip")
        info = await service.store_upload(upload, service.ASSET_FILE_LIMIT)
        imported = await run_in_threadpool(service.unpack_asset_zip, service.blob_path(info["sha256"]), folder) if is_zip else {name: info}
        if incoming.keys() & imported.keys():
            raise HTTPException(422, "Upload enthält doppelte Dateipfade")
        incoming.update(imported)
        if len(incoming) > service.ASSET_UPLOAD_FILES or sum(f["size"] for f in incoming.values()) > service.ASSET_UPLOAD_LIMIT:
            raise HTTPException(413, "Upload überschreitet 1000 Dateien oder 64 MiB entpackte Daten")
    mapping.update(incoming)
    if any(str(parent) in mapping for name in mapping for parent in PurePosixPath(name).parents):
        raise HTTPException(422, "Ein Dateipfad wird zugleich als Ordner verwendet")
    definition = service.editable_definition(previous)
    # Auto-discovered animation folders must include newly uploaded frames.
    for name, animation in definition.get("animations", {}).items():
        prefix = f"animations/{name}/"
        animation["frames"] = sorted(set(animation["frames"]) | {p for p in mapping if p.startswith(prefix)})
    service.publish(db, package, mapping, definition, expected)
    db.commit()
    return redir(f"/assets/{package.id}")

@router.post("/assets/{package_id}/files/delete")
def delete_file(package_id: str, path: str = Form(), expected: int = Form(), db: Session = Depends(get_db)):
    package = package_or_404(db, package_id)
    if package.kind in {"quiz", "communication"}:
        raise HTTPException(422, "Generierte Inhalte über den jeweiligen Inhaltseditor bearbeiten")
    previous = service.current(db, package)
    mapping = service.file_map(previous)
    if path not in mapping:
        raise HTTPException(404)
    del mapping[path]
    definition = service.editable_definition(previous)
    animations = definition.get("animations", {})
    definition["animations"] = {name: {**animation, "frames": [f for f in animation["frames"] if f != path]}
        for name, animation in animations.items() if any(f != path for f in animation["frames"])}
    if definition.get("preview") == path:
        definition.pop("preview")
    service.publish(db, package, mapping, definition, expected)
    db.commit()
    return redir(f"/assets/{package.id}")

@router.post("/assets/{package_id}/definition")
def edit_definition(package_id: str, definition: str = Form(), expected: int = Form(), db: Session = Depends(get_db)):
    package = package_or_404(db, package_id)
    if package.kind in {"quiz", "communication"}:
        raise HTTPException(422, "Diese Definition wird automatisch erzeugt")
    if len(definition) > 1_000_000:
        raise HTTPException(413)
    try:
        metadata = json.loads(definition)
    except ValueError:
        raise HTTPException(422, "Ungültiges JSON")
    service.publish(db, package, service.file_map(service.current(db, package)), metadata, expected)
    db.commit()
    return redir(f"/assets/{package.id}")

@router.post("/assets/{package_id}/quiz")
def edit_quiz(package_id: str, content: str = Form(), expected: int = Form(), db: Session = Depends(get_db)):
    package = package_or_404(db, package_id)
    if not package.catalog_id:
        raise HTTPException(422)
    if len(content) > 2_000_000:
        raise HTTPException(413)
    rows = service.parse_questions(content)
    catalog = db.get(QuizCatalog, package.catalog_id)
    catalog.questions = [QuizQuestion(question=q["q"], answers=q["a"], explanation=q["explanation"],
        min_age=q["minAge"], difficulty=q["difficulty"], tags=q["tags"]) for q in rows]
    db.flush()
    service.publish_quiz(db, package, catalog, expected)
    for device in db.scalars(select(Device)).all():
        if catalog in device.quiz_catalogs:
            device.quiz_version += 1
    db.commit()
    return redir(f"/assets/{package.id}")

@router.get("/firmware")
def firmware(request: Request, db: Session = Depends(get_db)):
    releases = db.scalars(select(FirmwareRelease)).all()
    releases.sort(key=lambda r: service.version_key(r.version), reverse=True)
    return templates.TemplateResponse(request, "firmware.html", {"releases": releases})

@router.post("/firmware")
async def upload_firmware(version: str = Form(), channel: str = Form(), notes: str = Form(""), file: UploadFile = File(), db: Session = Depends(get_db)):
    service.version_key(version)
    if channel not in {"stable", "beta"} or len(notes) > 20000:
        raise HTTPException(422)
    if db.scalar(select(FirmwareRelease).where(FirmwareRelease.version == version)):
        raise HTTPException(409, "Firmware-Version existiert bereits; Binary bleibt unverändert")
    if not file.filename or not file.filename.lower().endswith(".bin"):
        raise HTTPException(422, "Eine ESP32-S3 App-Binary (.bin) hochladen")
    info = await service.store_upload(file, 16 * 1024 * 1024)
    with service.blob_path(info["sha256"]).open("rb") as stream:
        header = stream.read(24)
    if len(header) < 24 or header[0] != 0xE9 or int.from_bytes(header[12:14], "little") != 9:
        raise HTTPException(422, "Keine ESP32-S3 App-Binary (kein vollständiges Flash-Image hochladen)")
    db.add(FirmwareRelease(version=version, channel=channel, notes=notes, **info))
    db.commit()
    return redir("/firmware")

@router.post("/firmware/{release_id}/promote")
def promote(release_id: int, db: Session = Depends(get_db)):
    release = db.get(FirmwareRelease, release_id)
    if not release:
        raise HTTPException(404)
    release.channel = "stable"
    db.commit()
    return redir("/firmware")


@router.post("/assets/{package_id}/questions")
def save_question(package_id: str, expected: int = Form(), question_id: int = Form(0), question: str = Form(),
                  answers: list[str] = Form(), explanation: str = Form(""), min_age: int = Form(0),
                  difficulty: int = Form(1), tags: str = Form(""), db: Session = Depends(get_db)):
    package = package_or_404(db, package_id)
    if not package.catalog_id:
        raise HTTPException(422)
    rows = service.parse_questions(json.dumps([{"q": question, "a": answers, "explanation": explanation,
        "minAge": min_age, "difficulty": difficulty, "tags": [t.strip() for t in tags.split(",") if t.strip()]}]))
    catalog = db.get(QuizCatalog, package.catalog_id)
    q = next((q for q in catalog.questions if q.id == question_id), None) if question_id else QuizQuestion()
    if q is None:
        raise HTTPException(404)
    row = rows[0]
    q.question, q.answers, q.explanation = row["q"], row["a"], row["explanation"]
    q.min_age, q.difficulty, q.tags = row["minAge"], row["difficulty"], row["tags"]
    if not question_id:
        catalog.questions.append(q)
    service.publish_quiz(db, package, catalog, expected)
    for device in db.scalars(select(Device)).all():
        if catalog in device.quiz_catalogs:
            device.quiz_version += 1
    db.commit()
    return redir(f"/assets/{package.id}")

@router.post("/assets/{package_id}/questions/{question_id}/delete")
def remove_question(package_id: str, question_id: int, expected: int = Form(), db: Session = Depends(get_db)):
    package = package_or_404(db, package_id)
    if not package.catalog_id:
        raise HTTPException(422)
    catalog = db.get(QuizCatalog, package.catalog_id)
    question = next((q for q in catalog.questions if q.id == question_id), None)
    if not question:
        raise HTTPException(404)
    catalog.questions.remove(question)
    service.publish_quiz(db, package, catalog, expected)
    for device in db.scalars(select(Device)).all():
        if catalog in device.quiz_catalogs:
            device.quiz_version += 1
    db.commit()
    return redir(f"/assets/{package.id}")
