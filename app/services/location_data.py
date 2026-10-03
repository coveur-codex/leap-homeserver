import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Device, LocationCache
from app.services.aircraft import AdsbLolProvider
from app.services.weather import OpenMeteoProvider


def location_key(latitude: float, longitude: float) -> str:
    return f"{latitude:.5f},{longitude:.5f}"


def configured_locations(db: Session) -> list[tuple[str, float, float]]:
    devices = db.scalars(select(Device).where(Device.enabled.is_(True), Device.latitude.is_not(None), Device.longitude.is_not(None))).all()
    locations = {}
    for device in devices:
        key = location_key(device.latitude, device.longitude)
        locations.setdefault(key, (device.weather_location, device.latitude, device.longitude))
    return list(locations.values())


def cache_for_device(device: Device, db: Session) -> LocationCache | None:
    if device.latitude is None or device.longitude is None:
        return None
    return db.scalar(select(LocationCache).where(LocationCache.location_key == location_key(device.latitude, device.longitude)))


def _fresh(fetched_at: datetime | None, now: datetime, kind: str = "weather") -> bool:
    if not fetched_at:
        return False
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    lifetime = timedelta(seconds=settings.aircraft_cache_seconds) if kind == "aircraft" else timedelta(minutes=settings.weather_cache_minutes)
    return fetched_at > now - lifetime


async def refresh_location(
    db: Session,
    location: str,
    latitude: float,
    longitude: float,
    *,
    weather_provider=None,
    aircraft_provider=None,
    force: bool = False,
) -> LocationCache:
    key = location_key(latitude, longitude)
    cache = db.scalar(select(LocationCache).where(LocationCache.location_key == key))
    if not cache:
        cache = LocationCache(location_key=key, location=location, latitude=latitude, longitude=longitude)
        db.add(cache)
        db.flush()
    else:
        cache.location = location or cache.location

    now = datetime.now(timezone.utc)
    fetch_weather = force or not _fresh(cache.weather_fetched_at, now)
    fetch_aircraft = force or not _fresh(cache.aircraft_fetched_at, now, "aircraft")
    tasks = []
    if fetch_weather:
        tasks.append(("weather", (weather_provider or OpenMeteoProvider()).current(latitude, longitude, "C")))
    if fetch_aircraft:
        tasks.append(("aircraft", (aircraft_provider or AdsbLolProvider()).nearby(latitude, longitude, settings.aircraft_radius_nm)))
    results = await asyncio.gather(*(task for _, task in tasks), return_exceptions=True)

    devices = db.scalars(select(Device).where(Device.enabled.is_(True))).all()
    matching = [device for device in devices if device.latitude is not None and device.longitude is not None and location_key(device.latitude, device.longitude) == key]
    for (kind, _), result in zip(tasks, results):
        if isinstance(result, Exception):
            setattr(cache, f"{kind}_error", str(result)[:1000])
            continue
        result["location"] = location
        setattr(cache, f"{kind}_data", result)
        setattr(cache, f"{kind}_fetched_at", now)
        setattr(cache, f"{kind}_error", None)
        for device in matching:
            setattr(device, f"{kind}_version", getattr(device, f"{kind}_version") + 1)
    db.commit()
    return cache


async def refresh_configured_locations(db: Session, *, weather_provider=None, aircraft_provider=None, force: bool = False) -> int:
    locations = configured_locations(db)
    for location, latitude, longitude in locations:
        await refresh_location(db, location, latitude, longitude, weather_provider=weather_provider, aircraft_provider=aircraft_provider, force=force)
    return len(locations)


async def data_for_device(device: Device, db: Session, kind: str) -> dict:
    if device.latitude is None or device.longitude is None:
        raise ValueError("Standort ist nicht konfiguriert")
    cache = cache_for_device(device, db)
    fetched_at = getattr(cache, f"{kind}_fetched_at", None) if cache else None
    data = getattr(cache, f"{kind}_data", None) if cache else None
    if not data or not _fresh(fetched_at, datetime.now(timezone.utc), kind):
        cache = await refresh_location(db, device.weather_location, device.latitude, device.longitude)
        data = getattr(cache, f"{kind}_data")
        fetched_at = getattr(cache, f"{kind}_fetched_at")
    if not data:
        raise RuntimeError(getattr(cache, f"{kind}_error") or f"{kind} nicht verfügbar")
    observed_at = fetched_at
    if kind == "aircraft":
        try:
            observed_at = datetime.fromisoformat(data.get("updated", "")).replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pass
    age = max(0, (datetime.now(timezone.utc) - observed_at.replace(tzinfo=timezone.utc)).total_seconds()) if observed_at else 121
    return {**data, "ageSeconds": age, "stale": not _fresh(fetched_at, datetime.now(timezone.utc), kind)}
