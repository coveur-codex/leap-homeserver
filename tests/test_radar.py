import io
import json
import math
import time

import httpx
import pytest
from PIL import Image

from app.core.config import settings
from app.models import Device
from app.services import radar


def tile():
    output = io.BytesIO()
    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    # An actual precipitation pixel fixture away from the centre marker.
    image.paste((0, 200, 40, 255), (105, 105, 120, 120))
    image.save(output, format="PNG")
    return output.getvalue()


@pytest.mark.asyncio
async def test_observation_cache_and_stale_fallback(db, monkeypatch):
    calls = []
    now = time.time()
    async def download(client, url, limit):
        calls.append(url)
        if url == radar.METADATA:
            return json.dumps({"radar": {"past": [{"time": int(now)-60, "path": "/v2/radar/123"}]}}).encode()
        assert url == radar.TILES + "/v2/radar/123/256/7/52.52000/13.40500/2/1_1.png"
        return tile()
    monkeypatch.setattr(radar, "_download", download)
    result = await radar.radar_for_location(52.52, 13.405)
    assert result["available"] and not result["stale"]
    assert result["source"] == "RainViewer"
    assert result["mapWidthKm"] == 50
    path = settings.data_dir / "images/weather-radar" / result["image"].rsplit("/", 1)[-1]
    with Image.open(path) as image:
        assert image.size == (112, 112) and image.mode == "RGB"
        assert image.getpixel((30, 30))[1] > 150
    assert await radar.radar_for_location(52.52, 13.405) == result
    assert len(calls) == 2
    async def fail(*args):
        raise httpx.ConnectError("provider offline")
    monkeypatch.setattr(radar, "_download", fail)
    monkeypatch.setattr(radar.time, "time", lambda: now + 1900)
    stale = await radar.radar_for_location(52.52, 13.405)
    assert stale["available"] and stale["stale"] and stale["image"] == result["image"]


@pytest.mark.asyncio
async def test_unavailable_is_not_a_synthetic_radar(db, monkeypatch):
    async def fail(*args):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(radar, "_download", fail)
    result = await radar.radar_for_location(52.52, 13.405)
    assert not result["available"] and "image" not in result
    assert not list((settings.data_dir / "images/weather-radar").glob("*.png"))


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["https://evil.test/radar", "/v2/radar/../secret", "/v2/radar/a?url=x"])
async def test_provider_paths_cannot_change_download_host(db, monkeypatch, path):
    calls = []
    async def download(client, url, limit):
        calls.append(url)
        return json.dumps({"radar": {"past": [{"time": int(time.time()), "path": path}]}}).encode()
    monkeypatch.setattr(radar, "_download", download)
    result = await radar.radar_for_location(52.52, 13.405)
    assert not result["available"] and calls == [radar.METADATA]


def test_radar_api_and_png(client, db, monkeypatch):
    device = Device(device_id="radar-device", name="Radar", latitude=52.52, longitude=13.405)
    db.add(device)
    db.commit()
    async def download(client, url, limit):
        if url == radar.METADATA:
            return json.dumps({"radar": {"past": [{"time": int(time.time()), "path": "/v2/radar/123"}]}}).encode()
        return tile()
    monkeypatch.setattr(radar, "_download", download)
    response = client.get("/api/v1/devices/radar-device/weather/radar")
    assert response.status_code == 200 and response.json()["available"]
    picture = client.get(response.json()["image"])
    assert picture.status_code == 200 and picture.headers["content-type"] == "image/png"
    assert int(picture.headers["content-length"]) == len(picture.content)
    assert client.get("/api/v1/assets/weather-radar/not-a-hash.png").status_code == 404
    device.enabled = False
    db.commit()
    assert client.get("/api/v1/devices/radar-device/weather/radar").status_code == 404
    device.enabled = True
    device.latitude = None
    db.commit()
    assert client.get("/api/v1/devices/radar-device/weather/radar").status_code == 422


@pytest.mark.parametrize("latitude", [0, 52.52, -52.52, 80, 85])
def test_coverage_matches_firmware_projection(latitude):
    zoom, pixels = radar.radar_crop(latitude)
    assert 0 <= zoom <= 7 and 0 < pixels <= 256
    km_per_pixel = radar.EARTH_CIRCUMFERENCE_KM * math.cos(math.radians(latitude)) / (256 * 2**zoom)
    assert pixels * km_per_pixel == pytest.approx(50)
    # Right edge longitude and top edge Mercator latitude for the same square.
    half_projected = 25 / math.cos(math.radians(latitude))
    edge_lon = math.degrees(half_projected / 6378.137)
    edge_lat = math.degrees(2 * math.atan(math.exp(
        math.asinh(math.tan(math.radians(latitude))) + half_projected / 6378.137)) - math.pi/2)
    assert math.radians(edge_lon) * 6378.137 * math.cos(math.radians(latitude)) == pytest.approx(25)
    assert (math.asinh(math.tan(math.radians(edge_lat))) - math.asinh(math.tan(math.radians(latitude)))) * 6378.137 * math.cos(math.radians(latitude)) == pytest.approx(25)
