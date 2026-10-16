"""Automatic shared, content-addressed 48px communication portraits."""
from io import BytesIO
import logging
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from app.models import AssetPackage, CommunicationRelayEvent
from app.services import distribution as assets

PACKAGE_ID = "communication-avatars"


def source_file(version):
    files = assets.file_map(version)
    paths = sorted(files)
    for path in paths:
        if path.lower().endswith("pagestatics/communication.png"):
            return files[path]
    definition = version.manifest["definition"]
    page_statics = definition.get("pageStatics", {})
    candidates = [page_statics.get("communication") if isinstance(page_statics, dict) else None,
                  definition.get("preview")]
    candidates += definition.get("animations", {}).get("idle", {}).get("frames", [])
    return next((files[p] for p in candidates if isinstance(p, str) and
                 p.lower().endswith(".png") and p in files), None)


def thumbnail(info):
    with Image.open(assets.blob_path(info["sha256"])) as image:
        if image.width * image.height > 20_000_000:
            raise ValueError("Avatar exceeds pixel limit")
        image = ImageOps.contain(image.convert("RGBA"), (48, 48), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (48, 48))
        canvas.alpha_composite(image, ((48-image.width)//2, (48-image.height)//2))
        out = BytesIO()
        canvas.save(out, "PNG", optimize=True)
        return assets.store_bytes(out.getvalue())


def ensure_package(db):
    package = db.get(AssetPackage, PACKAGE_ID)
    previous = assets.current(db, package) if package else None
    old_files = assets.file_map(previous)
    old_sources = previous.manifest["definition"].get("avatarSources", {}) if previous else {}
    sources, files = {}, {}
    for avatar in db.scalars(select(AssetPackage).where(AssetPackage.kind == "avatar").order_by(AssetPackage.id)):
        version = assets.current(db, avatar)
        info = source_file(version) if version else None
        if not info:
            continue
        old = old_sources.get(avatar.id, {})
        old_path = old.get("image", "") + ".png"
        if old.get("source") == info["sha256"] and old_path in old_files:
            portrait = old_files[old_path]
        else:
            try:
                portrait = thumbnail(info)
            except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
                logging.getLogger("leap").warning("communication_avatar_unreadable package=%s", avatar.id)
                continue
        digest = portrait["sha256"]
        files[digest + ".png"] = portrait
        sources[avatar.id] = {"source": info["sha256"], "image": digest}
    # A sender changing/deleting its avatar must not rewrite past message portraits.
    history = set(db.scalars(select(CommunicationRelayEvent.avatar_image).distinct()))
    for digest in history:
        path = digest + ".png"
        if digest and path in old_files:
            files[path] = old_files[path]
    if previous and sources == old_sources and files == old_files:
        return False
    if package is None:
        package = AssetPackage(id=PACKAGE_ID, kind="common", name="Nachrichtenavatare", current_version=0)
        db.add(package)
        db.flush()
    assets.publish(db, package, files, {"avatarSources": sources, "portraitSize": 48}, package.current_version)
    return True


def sender_image(db, device):
    ensure_package(db)
    package = db.get(AssetPackage, PACKAGE_ID)
    avatar = device.avatar if device.avatar.startswith("avatar-") else "avatar-" + device.avatar
    return assets.current(db, package).manifest["definition"]["avatarSources"].get(avatar, {}).get("image", "")
