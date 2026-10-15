"""Bounded LoremFlickr proxy. External URLs never come from a device or form."""
import asyncio
import hashlib
from io import BytesIO
from dataclasses import dataclass
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
PHOTO_READ_TIMEOUT = 60
PHOTO_TOTAL_TIMEOUT = 70
PHOTO_RESPONSE_WAIT = 1


class PhotoPending(ValueError):
    """The shared upstream fetch is still running; the device should retry later."""


@dataclass(frozen=True)
class PhotoDevice:
    id: int
    device_id: str
    chill_keyword: str

_locks: dict[int, asyncio.Lock] = {}
_recent: dict[int, tuple[float, str, dict | None]] = {}
_fetches: dict[int, tuple[str, asyncio.Task]] = {}


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
    async with httpx.AsyncClient(timeout=httpx.Timeout(PHOTO_READ_TIMEOUT, connect=5), follow_redirects=False) as client:
        for _ in range(6):
            if not safe_url(url):
                raise ValueError(f"Unzulässige Bildweiterleitung: {url.scheme}://{url.host}:{url.port or 443}")
            async with client.stream("GET", url, headers={"Accept": "image/jpeg,image/png"}) as response:
                if response.is_redirect:
                    if "location" not in response.headers:
                        raise ValueError("Bildweiterleitung ohne Ziel")
                    url = response.url.join(response.headers["location"])
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if content_type not in {"image/jpeg", "image/png"}:
                    raise ValueError(f"Ungültiger Bildtyp von {url.host}: {content_type[:80]!r}")
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


async def _fetch_photo(device: PhotoDevice) -> dict:
    topic = keyword(device.chill_keyword)
    async with _locks.setdefault(device.id, asyncio.Lock()):
        previous = _recent.get(device.id)
        now = time.monotonic()
        if previous and previous[1] == topic and now - previous[0] < 20:
            if previous[2] and photo_path(device.id, previous[2]["sha256"]).is_file():
                return previous[2]
            raise ValueError("Bilddienst wartet auf erneuten Versuch")
        _recent[device.id] = (now, topic, None)
        stage = "download"
        try:
            raw = await asyncio.wait_for(download(topic), timeout=PHOTO_TOTAL_TIMEOUT)
            stage = "decode"
            data = await asyncio.to_thread(convert, raw)
            digest = hashlib.sha256(data).hexdigest()
            path = photo_path(device.id, digest)
            stage = "cache"
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(".part")
            try:
                await asyncio.to_thread(temp.write_bytes, data)
                temp.replace(path)
            finally:
                temp.unlink(missing_ok=True)
            # Keep only the two most recent photos for each device, including after restarts.
            for old in sorted(path.parent.glob("*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True)[2:]:
                old.unlink(missing_ok=True)
            info = {"width": WIDTH, "height": HEIGHT, "size": len(data), "sha256": digest,
                    "url": f"/api/v1/devices/{quote(device.device_id, safe='')}/chill/photos/{digest}.jpg"}
        except (ValueError, TimeoutError, OSError, httpx.HTTPError) as error:
            _recent[device.id] = (time.monotonic(), topic, None)
            # Routes intentionally return a generic 503. Keep the actionable cause
            # here for both device requests and the browser preview, once per attempt.
            if isinstance(error, httpx.HTTPStatusError):
                reason = f"HTTP {error.response.status_code} from {error.request.url.host}"
            elif isinstance(error, httpx.RequestError):
                reason = str(error) or type(error).__name__
                try:
                    reason = f"{reason} from {error.request.url.host}"
                except RuntimeError:  # request-less synthetic errors in tests
                    pass
            else:
                reason = str(error) or type(error).__name__
            log.warning("chill_photo_failed device=%s stage=%s error=%s reason=%r",
                        device.device_id, stage, type(error).__name__, reason[:500])
            raise
        _recent[device.id] = (time.monotonic(), topic, info)
        log.info("chill_photo_ready device=%s bytes=%s", device.device_id, len(data))
        return info


def _observe_fetch(task: asyncio.Task):
    # A device can leave while a fetch is running. Consume errors even when no
    # subsequent request arrives; _fetch_photo already logged the actionable cause.
    if not task.cancelled():
        task.exception()


async def photo(device, *, wait: float | None = None) -> dict:
    topic = keyword(device.chill_keyword)
    pending = _fetches.get(device.id)
    if pending and pending[0] != topic:
        if not pending[1].done():
            raise PhotoPending("Ein vorheriger Bildabruf läuft noch")
        del _fetches[device.id]
        pending = None
    if pending is None:
        # Never retain a request-bound SQLAlchemy object after the route returns.
        snapshot = PhotoDevice(device.id, device.device_id, topic)
        task = asyncio.create_task(_fetch_photo(snapshot), name=f"chill-photo-{device.id}")
        task.add_done_callback(_observe_fetch)
        pending = (topic, task)
        _fetches[device.id] = pending
    task = pending[1]
    try:
        # A short device response budget is separate from the upstream budget.
        # Shield preserves one shared download across device timeouts/retries.
        return await asyncio.wait_for(asyncio.shield(task), timeout=PHOTO_RESPONSE_WAIT if wait is None else wait)
    except TimeoutError:
        if task.done():
            return task.result()  # propagate an actual upstream timeout
        raise PhotoPending("Bildabruf läuft; später erneut versuchen") from None
    finally:
        if task.done() and _fetches.get(device.id) is pending:
            del _fetches[device.id]


async def shutdown():
    tasks = [task for _, task in _fetches.values()]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    _fetches.clear()
