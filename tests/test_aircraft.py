from datetime import datetime, timedelta, timezone

import pytest

from app.models import LocationCache
from app.services import aircraft, location_data
from app.services.aircraft_names import airport_name


@pytest.mark.asyncio
async def test_provider_metric_names_routes_and_missing_data(monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {"ac": [
                {"hex": "abc", "flight": " TEST1 ", "t": "B738", "lat": 50.0, "lon": 7.01,
                 "alt_baro": 10000, "gs": 100, "track": 90, "seen_pos": 4,
                 "route": {"origin": "CGN", "destination": {"iata": "LHR"}}},
                {"hex": "def", "t": "ZZZZ", "lat": 50.0, "lon": 7.0, "alt_baro": "ground", "gs": 0},
                {"hex": "invalid", "lat": float("nan"), "lon": 7.0},
                {"hex": "far", "lat": 60, "lon": 7},
            ]}
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, *args, **kwargs): return Response()
    monkeypatch.setattr(aircraft.httpx, "AsyncClient", Client)
    result = await aircraft.AdsbLolProvider().nearby(50, 7, 25)
    assert result["center"] == {"latitude": 50, "longitude": 7}
    assert result["radiusKm"] == 46.3
    assert len(result["aircraft"]) == 2
    unknown, plane = result["aircraft"]
    assert plane["type"] == "B738" and plane["typeName"] == "Boeing 737-800"
    assert plane["altitudeMeters"] == 3048 and plane["groundSpeedKmh"] == 185
    assert plane["distanceKm"] == pytest.approx(plane["distanceNm"] * 1.852, abs=0.15)
    assert plane["originName"] == "Köln/Bonn" and plane["destinationName"] == "London Heathrow"
    assert plane["positionAgeSeconds"] == 4
    assert unknown["typeName"] == "Unbekannter Flugzeugtyp"
    assert unknown["groundSpeedKmh"] == 0 and unknown["altitudeMeters"] is None
    assert unknown["originName"] is None and unknown["destinationName"] is None


def test_airport_fallbacks():
    assert airport_name("EDDK") == "Köln/Bonn"
    assert airport_name({"name": "Test Airport", "iata": "XYZ"}) == "Test Airport"
    assert airport_name("XYZ") == "XYZ"
    assert airport_name(None) is None


@pytest.mark.asyncio
async def test_aircraft_cache_refresh_does_not_refresh_weather(db, monkeypatch):
    now = datetime.now(timezone.utc)
    db.add(LocationCache(location_key="50.00000,7.00000", latitude=50, longitude=7,
                         weather_fetched_at=now, weather_data={"current": {}},
                         aircraft_fetched_at=now - timedelta(seconds=31), aircraft_data={"aircraft": []}))
    db.commit()
    class Weather:
        async def current(self, *args): raise AssertionError("Weather is still fresh")
    class Aircraft:
        calls = 0
        async def nearby(self, *args):
            self.calls += 1
            return {"aircraft": [], "updated": now.isoformat()}
    provider = Aircraft()
    cache = await location_data.refresh_location(db, "Test", 50, 7, weather_provider=Weather(), aircraft_provider=provider)
    await location_data.refresh_location(db, "Test", 50, 7, weather_provider=Weather(), aircraft_provider=provider)
    assert provider.calls == 1
    assert cache.weather_data == {"current": {}}
    assert location_data._fresh(now - timedelta(seconds=29), now, "aircraft")
    assert not location_data._fresh(now - timedelta(seconds=31), now, "aircraft")
