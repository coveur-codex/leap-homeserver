"""Games page statics remain the source; publish only when their hashes change."""
from io import BytesIO
import logging
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from app.models import AssetPackage
from app.services import distribution as assets

PACKAGE_ID = "game-avatars"


def source_file(version):
    files = assets.file_map(version)
    canonical = "data/pet/pagestatics/games.png"
    paths = sorted(files, key=lambda p: (p != canonical, len(p), p))
    path = next((p for p in paths if p.lower().endswith("pagestatics/games.png")), None)
    if path is None:
        page = version.manifest["definition"].get("pageStatics", {})
        path = page.get("games") if isinstance(page, dict) else None
    return files.get(path)


def portrait(info):
    with Image.open(assets.blob_path(info["sha256"])) as image:
        if image.width * image.height > 20_000_000:
            raise ValueError("Avatar exceeds pixel limit")
        image.load()
        if image.size == (80,80) and (image.mode == "RGBA" or "transparency" in image.info):
            return info  # Keep already suitable PNG bytes and their content hash.
        image = ImageOps.contain(image.convert("RGBA"), (80,80), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (80,80))
        canvas.alpha_composite(image, ((80-image.width)//2,(80-image.height)//2))
        out = BytesIO()
        canvas.save(out, "PNG", optimize=True)
        return assets.store_bytes(out.getvalue())


def ensure_package(db):
    package = db.get(AssetPackage, PACKAGE_ID)
    previous = assets.current(db, package) if package else None
    old = previous.manifest["definition"].get("avatarSources", {}) if previous else {}
    old_files = assets.file_map(previous)
    sources, files = {}, {}
    for avatar in db.scalars(select(AssetPackage).where(AssetPackage.kind == "avatar").order_by(AssetPackage.id)):
        version = assets.current(db, avatar)
        source = source_file(version) if version else None
        if source is None:
            continue
        path = avatar.id + ".png"
        if old.get(avatar.id, {}).get("source") == source["sha256"] and path in old_files:
            info = old_files[path]
        else:
            try:
                info = portrait(source)
            except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
                logging.getLogger("leap").warning("game_avatar_unreadable package=%s", avatar.id)
                continue
        files[path] = info
        sources[avatar.id] = {"source":source["sha256"], "image":path}
    if previous and sources == old and files == old_files:
        return False
    if package is None:
        package = AssetPackage(id=PACKAGE_ID, kind="common", name="Spieleavatare", current_version=0)
        db.add(package)
        db.flush()
    assets.publish(db, package, files, {"avatarSources":sources, "portraitSize":80}, package.current_version)
    return True
