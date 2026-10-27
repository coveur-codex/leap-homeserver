"""Small shared photo library; each device owns its selected offline album package."""
from io import BytesIO
from uuid import uuid4
from starlette.concurrency import run_in_threadpool
from PIL import Image, ImageOps, UnidentifiedImageError
from fastapi import HTTPException
from sqlalchemy import select
from app.models import AssetPackage, ChillPhoto
from app.services import distribution as assets

MAX_PHOTOS = 24
MAX_UPLOAD = 8 * 1024 * 1024
MAX_PIXELS = 20_000_000


def convert(raw):
    try:
        with Image.open(BytesIO(raw)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"} or image.width * image.height > MAX_PIXELS:
                raise ValueError("Bild zu groß")
            image = ImageOps.fit(ImageOps.exif_transpose(image).convert("RGB"), (428, 142),
                                 method=Image.Resampling.LANCZOS)
            output = BytesIO()
            image.save(output, "JPEG", quality=82, optimize=True, progressive=False)
            return output.getvalue()
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        raise HTTPException(422, "Bild ist beschädigt oder überschreitet 20 Megapixel") from error


def library(db):
    return db.scalars(select(ChillPhoto).order_by(ChillPhoto.name, ChillPhoto.id)).all()


def publish(db, device, ids):
    ids = list(dict.fromkeys(ids))
    if not 1 <= len(ids) <= MAX_PHOTOS:
        raise HTTPException(422, f"Bitte 1–{MAX_PHOTOS} Bilder wählen")
    photos = [db.get(ChillPhoto, key) for key in ids]
    if any(photo is None for photo in photos):
        raise HTTPException(422, "Unbekanntes Bild")
    package = db.get(AssetPackage, device.chill_album_id) if device.chill_album_id else None
    if package is None:
        package = AssetPackage(id="chill-album-" + uuid4().hex, kind="chill",
                               name="Eigene Bilder · " + device.name, current_version=0)
        db.add(package)
        db.flush()
        device.chill_album_id = package.id
    device.chill_photos = ids
    files = {f"photos/{p.id}.jpg": {"sha256": p.id, "size": p.size} for p in photos}
    paths = list(files)
    assets.publish(db, package, files, {"scene": "album", "minFirmware": "1.1.2",
        "slider": {"min": 0, "max": 300, "default": 200}, "sprites": [],
        "photos": paths, "preview": paths[0]}, package.current_version)
    device.config_version += 1
    return package


async def upload(db, device, uploads):
    if not 1 <= len(uploads) <= MAX_PHOTOS:
        raise HTTPException(422, f"Höchstens {MAX_PHOTOS} Dateien je Upload")
    converted = []
    try:
        for upload in uploads:
            raw = await upload.read(MAX_UPLOAD + 1)
            if len(raw) > MAX_UPLOAD:
                raise HTTPException(413, "Ein Bild darf höchstens 8 MiB groß sein")
            # Original bytes/EXIF are never persisted.
            converted.append((str(upload.filename or "Bild")[:120], await run_in_threadpool(convert, raw)))
    finally:
        for upload in uploads:
            await upload.close()
    import hashlib
    ids = list(device.chill_photos or [])
    for _, data in converted:
        digest = hashlib.sha256(data).hexdigest()
        if digest not in ids:
            ids.append(digest)
    if len(ids) > MAX_PHOTOS:
        raise HTTPException(422, f"Im Album sind höchstens {MAX_PHOTOS} Bilder möglich")
    for name, data in converted:
        info = assets.store_bytes(data)
        if not db.get(ChillPhoto, info["sha256"]):
            db.add(ChillPhoto(id=info["sha256"], name=name, size=info["size"]))
            db.flush()
    return publish(db, device, ids)
