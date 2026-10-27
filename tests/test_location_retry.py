import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Device, LocationCache
from app.services import location_data


class Weather:
    async def current(self, *args):
        return {"current": {}}


@pytest.mark.asyncio
@pytest.mark.parametrize("retry_after", ["3600", "date", "invalid", None])
async def test_retry_pause_survives_sessions_and_serves_stale_data(db, monkeypatch, retry_after):
    now = datetime.now(timezone.utc)
    if retry_after == "date":
        retry_after = format_datetime(now + timedelta(hours=1), usegmt=True)
    calls = 0

    class Aircraft:
        async def nearby(self, *args):
            nonlocal calls
            calls += 1
            response = httpx.Response(429, headers={"Retry-After": retry_after} if retry_after else {},
                                      request=httpx.Request("GET", "https://api.adsb.lol/test"))
            response.raise_for_status()

    monkeypatch.setattr(location_data, "OpenMeteoProvider", Weather)
    monkeypatch.setattr(location_data, "AdsbLolProvider", Aircraft)
    device = Device(device_id="one", name="One", latitude=50.8137, longitude=7.0352)
    cache = LocationCache(location_key=location_data.location_key(device.latitude, device.longitude),
                          latitude=device.latitude, longitude=device.longitude,
                          aircraft_data={"aircraft": [{"hex": "abc"}]},
                          aircraft_fetched_at=now - timedelta(days=1))
    db.add_all([device, cache]); db.commit()
    version = device.aircraft_version
    result = await location_data.data_for_device(device, db, "aircraft")
    assert result["stale"] is True and result["aircraft"] == [{"hex": "abc"}]
    assert "HTTP 429" in cache.aircraft_error
    expected_seconds = 3599 if retry_after and retry_after != "invalid" else settings.weather_cache_minutes * 60
    assert cache.aircraft_next_attempt_at.replace(tzinfo=timezone.utc) >= now + timedelta(seconds=expected_seconds)
    # Simulate another request/process using a new session, including no cached payload.
    cache.aircraft_data = None
    db.commit()
    with Session(db.bind) as other:
        other_device = other.get(Device, device.id)
        with pytest.raises(RuntimeError, match="HTTP 429"):
            await location_data.data_for_device(other_device, other, "aircraft")
    assert calls == 1 and device.aircraft_version == version
    # Once due, the API may be tried again.
    cache.aircraft_next_attempt_at = now - timedelta(seconds=1)
    db.commit()
    await location_data.refresh_configured_locations(db)
    assert calls == 2


@pytest.mark.asyncio
async def test_overlapping_refreshes_reserve_one_request(db):
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    class Aircraft:
        async def nearby(self, *args):
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return {"aircraft": []}

    device = Device(device_id="one", name="One", latitude=50.8137, longitude=7.0352)
    db.add(device); db.commit()
    first = asyncio.create_task(location_data.refresh_configured_locations(db, weather_provider=Weather(), aircraft_provider=Aircraft()))
    await started.wait()
    try:
        with Session(db.bind) as other:
            await location_data.refresh_configured_locations(other, weather_provider=Weather(), aircraft_provider=Aircraft())
        assert calls == 1
    finally:
        release.set()
        await first


def test_system_page_uses_retry_time(client, db):
    retry_at = datetime(2026, 10, 27, 20, 0, tzinfo=timezone.utc)
    db.add(LocationCache(location_key="50.81370,7.03520", latitude=50.8137, longitude=7.0352,
                         aircraft_next_attempt_at=retry_at, aircraft_error="API-Anfragelimit erreicht (HTTP 429)."))
    db.commit()
    page = client.get("/system")
    assert "27.10.2026, 20:00:00" in page.text and "HTTP 429" in page.text


@pytest.mark.asyncio
async def test_success_keeps_aircraft_interval_and_clears_error(db):
    class Aircraft:
        async def nearby(self, *args):
            return {"aircraft": []}

    past = datetime.now(timezone.utc) - timedelta(days=1)
    cache = LocationCache(location_key="50.81370,7.03520", latitude=50.8137, longitude=7.0352,
                          aircraft_error="HTTP 429", aircraft_next_attempt_at=past)
    db.add(cache); db.commit()
    await location_data.refresh_location(db, "Test", cache.latitude, cache.longitude,
                                         weather_provider=Weather(), aircraft_provider=Aircraft())
    assert cache.aircraft_error is None
    assert (cache.aircraft_next_attempt_at - cache.aircraft_fetched_at).total_seconds() == settings.aircraft_cache_seconds
    assert (cache.weather_next_attempt_at - cache.weather_fetched_at).total_seconds() == settings.weather_cache_minutes * 60
