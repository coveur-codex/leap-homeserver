"""Small, cached RainViewer observation images; no synthetic precipitation."""
import asyncio
import hashlib
import io
import json
import math
import re
import time
from datetime import datetime, timezone

import httpx
from PIL import Image, ImageDraw

from app.core.config import settings

# Provider-controlled paths are validated and resolved only on this fixed host.
METADATA = "https://api.rainviewer.com/public/weather-maps.json"
TILES = "https://tilecache.rainviewer.com"
_lock = asyncio.Lock()
RADAR_WIDTH_KM = 50.0
EARTH_CIRCUMFERENCE_KM = 40075.016686


def radar_crop(latitude: float) -> tuple[int, float]:
    """Mercator square spanning 50 km at the centre latitude, north up.

    RainViewer's geographic-centre endpoint returns 256 pixels at the selected
    zoom. Crop before resizing; a fixed zoom alone changes coverage by latitude.
    """
    circumference = EARTH_CIRCUMFERENCE_KM * math.cos(math.radians(latitude))
    zoom = max(0, min(7, math.floor(math.log2(circumference / RADAR_WIDTH_KM))))
    pixels = 256 * RADAR_WIDTH_KM * 2**zoom / circumference
    return zoom, pixels


def _cleanup(root, now):
    # Preserve the current (possibly stale) frame for every cached location.
    referenced = set()
    for meta in root.glob("*.json"):
        try:
            referenced.add(json.loads(meta.read_text()).get("image", "").rsplit("/", 1)[-1])
        except (OSError, ValueError, AttributeError):
            continue
    for image in root.glob("*.png"):
        if image.name not in referenced and image.stat().st_mtime < now - 172800:
            image.unlink(missing_ok=True)


async def _download(client, url, limit):
    async with client.stream("GET", url) as response:
        response.raise_for_status()
        data = bytearray()
        async for chunk in response.aiter_bytes():
            data.extend(chunk)
            if len(data) > limit:
                raise ValueError("Radar response too large")
        return bytes(data)


async def radar_for_location(latitude: float, longitude: float) -> dict:
    if not (math.isfinite(latitude) and math.isfinite(longitude)
            and -85 <= latitude <= 85 and -180 <= longitude <= 180):
        raise ValueError("Standort außerhalb der Radar-Karte")
    key = hashlib.sha256(f"50km-v1:{latitude:.5f},{longitude:.5f}".encode()).hexdigest()
    root = settings.data_dir / "images" / "weather-radar"
    root.mkdir(parents=True, exist_ok=True)
    meta = root / f"{key}.json"
    async with _lock:
        now = time.time()
        try:
            cached = json.loads(meta.read_text())
        except (OSError, ValueError):
            cached = {}
        if now - cached.get("checkedAt", 0) >= 600:
            try:
                async with asyncio.timeout(4), httpx.AsyncClient(timeout=settings.request_timeout) as client:
                    manifest = json.loads(await _download(client, METADATA, 128_000))
                    frames = manifest["radar"]["past"]
                    frame = max(frames, key=lambda f: int(f["time"]))
                    stamp = int(frame["time"])
                    if stamp > now + 300 or stamp < now - 7200:
                        raise ValueError("Radar observation is out of date")
                    path = frame["path"]
                    if not re.fullmatch(r"/v2/radar/[A-Za-z0-9_/-]+", path) or ".." in path:
                        raise ValueError("Invalid radar tile path")
                    # Geographic-centre API: the configured location is the centre pixel.
                    zoom, crop_pixels = radar_crop(latitude)
                    url = f"{TILES}{path}/256/{zoom}/{latitude:.5f}/{longitude:.5f}/2/1_1.png"
                    raw = await _download(client, url, 512_000)
                with Image.open(io.BytesIO(raw)) as source:
                    if source.size != (256, 256) or source.format != "PNG":
                        raise ValueError("Invalid radar tile")
                    half = crop_pixels / 2
                    tile = source.convert("RGBA").transform(
                        (112, 112), Image.Transform.EXTENT,
                        (128-half, 128-half, 128+half, 128+half),
                        Image.Resampling.BICUBIC)
                image = Image.new("RGBA", (112, 112), "#152c3b")
                draw = ImageDraw.Draw(image)
                for radius in (18, 36, 54):
                    draw.ellipse((56-radius, 56-radius, 56+radius, 56+radius), outline="#385363")
                draw.line((56, 0, 56, 111), fill="#385363")
                draw.line((0, 56, 111, 56), fill="#385363")
                image = Image.alpha_composite(image, tile)
                draw = ImageDraw.Draw(image)
                draw.ellipse((53, 53, 59, 59), fill="white", outline="#182d3c")
                draw.text((3, 1), "N", fill="white")
                output = io.BytesIO()
                image.convert("RGB").save(output, format="PNG")
                data = output.getvalue()
                digest = hashlib.sha256(data).hexdigest()
                target = root / f"{digest}.png"
                temporary = root / f"{digest}.tmp"
                temporary.write_bytes(data)
                temporary.replace(target)
                cached = {"available": True, "image": f"/api/v1/assets/weather-radar/{digest}.png",
                          "updated": datetime.fromtimestamp(stamp, timezone.utc).isoformat(),
                          "timestamp": stamp, "source": "RainViewer", "sourceUrl": "https://www.rainviewer.com/",
                          "latitude": latitude, "longitude": longitude, "mapWidthKm": RADAR_WIDTH_KM}
            except (httpx.HTTPError, ValueError, KeyError, TypeError, OSError, TimeoutError):
                # Keep the last observation, clearly labelled stale; weather stays usable.
                cached["stale"] = True
            cached["checkedAt"] = now
            temporary = meta.with_suffix(".tmp")
            temporary.write_text(json.dumps(cached))
            temporary.replace(meta)
            _cleanup(root, now)
        available = bool(cached.get("image")) and (root / cached["image"].rsplit("/", 1)[-1]).is_file()
        return {**{k: v for k, v in cached.items() if k not in {"checkedAt", "timestamp"}},
                "available": available,
                "stale": cached.get("stale", False) or now - cached.get("timestamp", 0) > 1800}
