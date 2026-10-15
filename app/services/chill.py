"""Bounded LoremFlickr proxy. External URLs never come from a device or form."""
import asyncio
import hashlib
from io import BytesIO
import logging
import re
import secrets
import time
from urllib.parse import quote

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError
from app.core.config import settings

log = logging.getLogger(__name__)
WIDTH, HEIGHT = 428, 142  # NV3007's configured landscape orientation
PACKAGE_ID = "chill-loremflickr"
MAX_DOWNLOAD = 4 * 1024 * 1024
MAX_PIXELS = 20_000_000
_locks: dict[int, asyncio.Lock] = {}
_recent: dict[int, tuple[float, str, dict | None]] = {}


def keyword(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 80 or not re.fullmatch(r"[\w -]+(?:,[\w -]+)*", value, re.UNICODE):
        raise ValueError("Thema: 1–80 Buchstaben, Zahlen, Leerzeichen, Bindestriche oder kommagetrennte Begriffe")
    return value


def safe_url(url: httpx.URL) -> bool:
    host = url.host.lower()
    return (url.scheme == "https" and url.port in {None, 443} and not url.userinfo
            and (host in {"loremflickr.com", "www.loremflickr.com"}
                 or host == "live.staticflickr.com"
                 or re.fullmatch(r"farm[0-9]+\.staticflickr\.com", host) is not None))


async def download(topic: str) -> bytes:
    # A fresh random parameter bypasses LoremFlickr's cached random-photo selection.
    url = httpx.URL(f"https://loremflickr.com/{WIDTH}/{HEIGHT}/{quote(topic, safe=',')}?random={secrets.randbits(48)}")
    async with httpx.AsyncClient(timeout=httpx.Timeout(12, connect=5), follow_redirects=False) as client:
        for _ in range(6):
            if not safe_url(url):
                raise ValueError("Unzulässige Bildweiterleitung")
            async with client.stream("GET", url, headers={"Accept": "image/jpeg,image/png"}) as response:
                if response.is_redirect:
                    if "location" not in response.headers:
                        raise ValueError("Bildweiterleitung ohne Ziel")
                    url = response.url.join(response.headers["location"])
                    continue
                response.raise_for_status()
                if response.headers.get("content-type", "").split(";")[0].lower() not in {"image/jpeg", "image/png"}:
                    raise ValueError("Ungültiger Bildtyp")
                if int(response.headers.get("content-length", 0)) > MAX_DOWNLOAD:
                    raise ValueError("Bild zu groß")
                chunks = bytearray()
                async for chunk in response.aiter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > MAX_DOWNLOAD:
                        raise ValueError("Bild zu groß")
                return bytes(chunks)
    raise ValueError("Zu viele Bildweiterleitungen")


def convert(raw: bytes) -> bytes:
    try:
        with Image.open(BytesIO(raw)) as source:
            if source.format not in {"JPEG", "PNG"} or source.width * source.height > MAX_PIXELS:
                raise ValueError("Nicht unterstütztes Bild")
            source = ImageOps.exif_transpose(source).convert("RGB")
            image = ImageOps.fit(source, (WIDTH, HEIGHT), method=Image.Resampling.LANCZOS)
            output = BytesIO()
            image.save(output, "JPEG", quality=85, optimize=True, progressive=False)
            data = output.getvalue()
            if len(data) > 128 * 1024:
                raise ValueError("Gerätebild zu groß")
            return data
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError("Ungültige Bilddaten") from error


def photo_path(device_id: int, digest: str):
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("Ungültige Bild-ID")
    return settings.data_dir / "images" / "chill" / str(device_id) / f"{digest}.jpg"


async def photo(device) -> dict:
    topic = keyword(device.chill_keyword)
    async with _locks.setdefault(device.id, asyncio.Lock()):
        previous = _recent.get(device.id)
        now = time.monotonic()
        if previous and previous[1] == topic and now - previous[0] < 20:
            if previous[2] and photo_path(device.id, previous[2]["sha256"]).is_file():
                return previous[2]
            raise ValueError("Bilddienst wartet auf erneuten Versuch")
        _recent[device.id] = (now, topic, None)
        raw = await asyncio.wait_for(download(topic), timeout=25)
        data = await asyncio.to_thread(convert, raw)
        digest = hashlib.sha256(data).hexdigest()
        path = photo_path(device.id, digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".part")
        try:
            await asyncio.to_thread(temp.write_bytes, data)
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)
        info = {"width": WIDTH, "height": HEIGHT, "size": len(data), "sha256": digest,
                "url": f"/api/v1/devices/{quote(device.device_id, safe='')}/chill/photos/{digest}.jpg"}
        _recent[device.id] = (now, topic, info)
        # Keep only the two most recent photos for each device, including after restarts.
        for old in sorted(path.parent.glob("*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True)[2:]:
            old.unlink(missing_ok=True)
        log.info("chill_photo_ready device=%s bytes=%s", device.device_id, len(data))
        return info
