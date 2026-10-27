from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models import Device
from app.services.device_settings import server_url, target_numbers, wifi_profile, DEFAULT_SERVER

router = APIRouter()

def device(db, id):
    d = db.get(Device, id)
    if not d: raise HTTPException(404, "Gerät nicht gefunden")
    return d

def save(db, d, config):
    config["revision"] = int((d.network_config or {}).get("revision", 0)) + 1
    d.network_config = config
    d.config_version += 1
    db.commit()
    return RedirectResponse(f"/devices/{d.id}#network", 303)

@router.post("/devices/{id}/network")
def network(id: int, server: str = Form(DEFAULT_SERVER), db: Session = Depends(get_db)):
    d = device(db, id)
    try: url = server_url(server)
    except ValueError as e: raise HTTPException(422, str(e))
    return save(db, d, {**(d.network_config or {}), "serverUrl":url})

@router.post("/devices/{id}/network/wifi")
def wifi(id: int, ssid: str = Form(), password: str = Form(""), db: Session = Depends(get_db)):
    d = device(db, id)
    try: profile = wifi_profile(ssid, password)
    except ValueError as e: raise HTTPException(422, str(e))
    config = dict(d.network_config or {})
    profiles = list(config.get("wifiProfiles", []))
    if not any(p["ssid"] == ssid for p in profiles) and len(profiles) >= 4:
        raise HTTPException(422, "Maximal vier WLAN-Profile je Gerät am Server")
    # First entry has highest priority; resaving moves a profile to the front.
    config["wifiProfiles"] = [profile] + [p for p in profiles if p["ssid"] != ssid]
    return save(db, d, config)

@router.post("/devices/{id}/network/remove")
def remove(id: int, ssid: str = Form(), db: Session = Depends(get_db)):
    d = device(db, id); config = dict(d.network_config or {})
    config["wifiProfiles"] = [p for p in config.get("wifiProfiles", []) if p["ssid"] != ssid]
    return save(db, d, config)

@router.post("/devices/{id}/math-lab")
def math_lab(id: int, targets: str = Form(), db: Session = Depends(get_db)):
    d = device(db, id)
    try: numbers = target_numbers(targets)
    except ValueError as e: raise HTTPException(422, str(e))
    d.math_lab = {"targets":numbers}; d.config_version += 1; db.commit()
    return RedirectResponse(f"/devices/{id}#math-lab", 303)

@router.get("/api/v1/devices/{device_id}/network-config")
def network_config(device_id: str, db: Session = Depends(get_db)):
    from app.api.routes import device_or_404
    d = device_or_404(device_id, db)
    config = d.network_config or {}
    # Separate from offline content snapshots and the general configuration.
    return JSONResponse({"schemaVersion":1, "deviceId":d.device_id,
        "revision":config.get("revision", 0), "serverUrl":config.get("serverUrl", DEFAULT_SERVER),
        "wifiProfiles":config.get("wifiProfiles", [])}, headers={"Cache-Control":"no-store"})
