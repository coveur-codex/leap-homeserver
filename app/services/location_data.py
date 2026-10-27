import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx

from sqlalchemy import or_, select, update
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


def _fresh(fetched_at: datetime | None, now: datetime) -> bool:
    if not fetched_at:
        return False
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    return fetched_at > now - timedelta(minutes=settings.weather_cache_minutes)


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
    tasks = []
    # Reserve each due request in the database before awaiting network I/O.
    # This also prevents the scheduler and device requests from fetching together.
    for kind in ("weather", "aircraft"):
        if not force and _fresh(getattr(cache, f"{kind}_fetched_at"), now):
            continue
        next_attempt = getattr(LocationCache, f"{kind}_next_attempt_at")
        claimed = db.execute(
            update(LocationCache).where(
                LocationCache.id == cache.id,
                or_(next_attempt.is_(None), next_attempt <= now),
            ).values({f"{kind}_next_attempt_at": now + timedelta(
                seconds=max(settings.weather_cache_minutes * 60, settings.request_timeout + 1)
            )}), execution_options={"synchronize_session": False},
        ).rowcount
        if claimed:
            tasks.append(kind)
    db.commit()
    db.refresh(cache)
    tasks = [(kind, (weather_provider or OpenMeteoProvider()).current(latitude, longitude, "C")
              if kind == "weather" else
              (aircraft_provider or AdsbLolProvider()).nearby(latitude, longitude, settings.aircraft_radius_nm))
             for kind in tasks]
    results = await asyncio.gather(*(task for _, task in tasks), return_exceptions=True)

    devices = db.scalars(select(Device).where(Device.enabled.is_(True))).all()
    matching = [device for device in devices if device.latitude is not None and device.longitude is not None and location_key(device.latitude, device.longitude) == key]
    for (kind, _), result in zip(tasks, results):
        completed_at = datetime.now(timezone.utc)
        next_attempt = completed_at + timedelta(minutes=settings.weather_cache_minutes)
        if isinstance(result, httpx.HTTPStatusError) and result.response.status_code == 429:
            retry_after = result.response.headers.get("Retry-After", "")
            try:
                retry_at = completed_at + timedelta(seconds=int(retry_after))
            except (ValueError, OverflowError):
                try:
                    retry_at = parsedate_to_datetime(retry_after)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=timezone.utc)
                except (ValueError, TypeError, OverflowError):
                    retry_at = next_attempt
            next_attempt = max(next_attempt, retry_at)
        setattr(cache, f"{kind}_next_attempt_at", next_attempt)
        if isinstance(result, Exception):
            error = str(result)
            if isinstance(result, httpx.HTTPStatusError) and result.response.status_code == 429:
                error = "API-Anfragelimit erreicht (HTTP 429). Erneuter Abruf frühestens " + next_attempt.strftime("%d.%m.%Y, %H:%M:%S UTC")
            setattr(cache, f"{kind}_error", error[:1000])
            continue
        result["location"] = location
        setattr(cache, f"{kind}_data", result)
        setattr(cache, f"{kind}_fetched_at", completed_at)
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
    if not data or not _fresh(fetched_at, datetime.now(timezone.utc)):
        cache = await refresh_location(db, device.weather_location, device.latitude, device.longitude)
        data = getattr(cache, f"{kind}_data")
        fetched_at = getattr(cache, f"{kind}_fetched_at")
    if not data:
        raise RuntimeError(getattr(cache, f"{kind}_error") or f"{kind} nicht verfügbar")
    return {**data, "stale": not _fresh(fetched_at, datetime.now(timezone.utc))}
