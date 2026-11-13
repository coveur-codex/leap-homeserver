"""Central stations and explicit per-device grants in the existing config snapshot."""
from urllib.parse import urlsplit, urlunsplit
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Device, RadioStation

MAX_STATIONS = 32

def validate_station(name: str, url: str, position: int) -> tuple[str, str]:
    name, url = name.strip(), url.strip()
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme in {"http", "https"} and parsed.hostname and
                 not parsed.username and not parsed.password and not parsed.fragment)
        parsed.port
    except ValueError:
        valid = False
    if (not name or len(name.encode("utf-8")) > 120 or len(url.encode("utf-8")) > 1000 or
        not valid or "#" in url or "\\" in url or any(ord(c) <= 32 or ord(c) == 127 for c in url) or
        any(ord(c) < 32 for c in name) or not 1 <= position <= 9999):
        raise HTTPException(422, "Name, Position und direkte HTTP(S)-MP3-Stream-URL prüfen")
    if parsed.path.lower().endswith((".m3u", ".m3u8", ".pls", ".aac", ".ogg", ".flac", ".wav")):
        raise HTTPException(422, "Nur direkte MP3-Streams, keine Playlists oder anderen Audioformate")
    return name, urlunsplit(parsed)

def stations(db: Session):
    return db.scalars(select(RadioStation).order_by(RadioStation.position, RadioStation.id)).all()

def for_device(device: Device, db: Session) -> list[dict]:
    if not any(p.page_id == "radio" and p.enabled for p in device.pages):
        return []
    allowed = set(device.radio_station_ids or [])
    return [{"id": s.id, "name": s.name, "url": s.url} for s in stations(db)
            if s.enabled and s.id in allowed]

def bump_assigned(db: Session, station_id: int, *, delete: bool = False):
    for device in db.scalars(select(Device)).all():
        if station_id in (device.radio_station_ids or []):
            if delete:
                device.radio_station_ids = [x for x in device.radio_station_ids if x != station_id]
            device.config_version += 1
