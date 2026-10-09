from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.routes import device_or_404
from app.core.database import get_db
from app.models import AssetPackage, AssetVersion, FirmwareRelease, SyncRun, SyncEvent
from app.services import distribution as service

router = APIRouter(prefix="/api/v1")

class BootReport(BaseModel):
    firmwareVersion: str = Field(min_length=1, max_length=40)
    firmwareChannel: Literal["stable", "beta"] | None = None
    deviceConfigSchema: int = Field(0, ge=0, le=1)
    installedAssets: dict[str, int] = Field(default_factory=dict, max_length=500)
    freeFlash: int | None = Field(None, ge=0)

class EventReport(BaseModel):
    event: Literal["download_started", "asset_installed", "firmware_installed", "boot_success",
                   "firmware_confirmed", "sync_success", "update_failed", "checksum_failed", "download_aborted", "rollback"]
    packageId: str | None = Field(None, max_length=100)
    version: int | None = Field(None, ge=1)
    firmwareVersion: str | None = Field(None, max_length=40)
    installedAssets: dict[str, int] | None = Field(None, max_length=500)
    message: str = Field("", max_length=2000)


def manifest_row(db, package_id, version):
    row = db.scalar(select(AssetVersion).where(AssetVersion.package_id == package_id, AssetVersion.version == version))
    if not row:
        raise HTTPException(404, "Paketversion nicht gefunden")
    return row

@router.get("/packages/{package_id}/versions/{version}/manifest")
def manifest(package_id: str, version: int, db: Session = Depends(get_db)):
    return manifest_row(db, package_id, version).manifest

@router.get("/packages/{package_id}/versions/{version}/files/{path:path}")
def asset_file(package_id: str, version: int, path: str, db: Session = Depends(get_db)):
    row = manifest_row(db, package_id, version)
    item = next((f for f in row.manifest["files"] if f["path"] == path), None)
    if not item or not service.blob_path(item["sha256"]).is_file():
        raise HTTPException(404)
    suffix = path.rsplit(".", 1)[-1].lower()
    media = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "svg": "image/svg+xml", "webp": "image/webp", "gif": "image/gif", "json": "application/json", "wav": "audio/wav", "mp3": "audio/mpeg"}.get(suffix, "application/octet-stream")
    return FileResponse(service.blob_path(item["sha256"]), media_type=media, headers={
        "Cache-Control": "public, max-age=31536000, immutable", "ETag": '"' + item["sha256"] + '"',
        "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox; default-src 'none'"})

@router.get("/firmware/{release_id}/binary")
def firmware_binary(release_id: int, db: Session = Depends(get_db)):
    release = db.get(FirmwareRelease, release_id)
    if not release or release.withdrawn or release.deleted or not service.blob_path(release.sha256).is_file():
        raise HTTPException(404)
    return FileResponse(service.blob_path(release.sha256), media_type="application/octet-stream",
                        filename=f"leap-{release.version}.bin", headers={"ETag": '"' + release.sha256 + '"',
                        "Cache-Control": "no-store"})

@router.post("/devices/{device_id}/sync")
def boot_sync(device_id: str, report: BootReport, db: Session = Depends(get_db)):
    device = device_or_404(device_id, db)
    if any(len(key) > 100 or value < 1 for key, value in report.installedAssets.items()):
        raise HTTPException(422, "Ungültiges Asset-Inventar")
    service.ensure_packages(db)
    device.last_sync = device.last_seen = datetime.now(timezone.utc)
    device.firmware_version = report.firmwareVersion
    device.installed_assets = report.installedAssets
    device.free_flash = report.freeFlash
    desired, updates, blocked = {}, [], []
    for package in service.desired_packages(db, device):
        row = service.current(db, package)
        desired[package.id] = package.current_version
        minimum = row.manifest["definition"].get("minFirmware")
        compatible = True
        if minimum:
            try:
                compatible = service.version_key(report.firmwareVersion) >= service.version_key(minimum)
            except HTTPException:
                compatible = False
        if not compatible:
            blocked.append({"packageId": package.id, "minFirmware": minimum})
        elif report.installedAssets.get(package.id) != package.current_version:
            updates.append({"packageId": package.id, "version": package.current_version,
                            "manifestUrl": f"/api/v1/packages/{package.id}/versions/{package.current_version}/manifest",
                            "downloadBytes": sum(f["size"] for f in row.manifest["files"])})
    plan = {"configVersion": device.config_version, "configUrl": f"/api/v1/devices/{device_id}/config",
            "firmwareChannel": device.firmware_channel, "firmware": (service.firmware_offer(db, device, report.firmwareVersion)
                         if report.deviceConfigSchema == 1 else None),
            "initialFirmware": report.firmwareVersion, "desiredAssets": desired, "assetUpdates": updates,
            "blockedAssets": blocked, "previousAssets": report.installedAssets,
            "cleanupAllowed": False, "cleanupAfter": "boot_success", "strategy": "stage-verify-activate-confirm-cleanup"}
    run = SyncRun(id=str(uuid4()), device_id=device.id, plan=plan, status="offered")
    db.add(run); db.flush()
    db.add(SyncEvent(run_id=run.id, event="offered", details={"assets": len(updates), "firmware": bool(plan["firmware"])}))
    db.commit()
    return {"syncId": run.id, **plan}

@router.post("/devices/{device_id}/sync/{sync_id}/events")
def sync_event(device_id: str, sync_id: str, report: EventReport, db: Session = Depends(get_db)):
    device = device_or_404(device_id, db)
    run = db.get(SyncRun, sync_id)
    if not run or run.device_id != device.id:
        raise HTTPException(404)
    latest = db.scalar(select(SyncRun.id).where(SyncRun.device_id == device.id).order_by(SyncRun.created_at.desc()).limit(1))
    if latest != run.id:
        raise HTTPException(409, "Dieser Sync wurde durch einen neueren ersetzt")
    plan = run.plan
    failures = {"update_failed", "checksum_failed", "download_aborted", "rollback"}
    if run.status in failures or run.status == "sync_success":
        raise HTTPException(409, "Sync abgeschlossen; neuen Start-Sync anfordern")
    cleanup = []
    if report.event == "asset_installed":
        if plan["desiredAssets"].get(report.packageId) != report.version or report.packageId is None:
            raise HTTPException(422, "Paketversion gehört nicht zu diesem Update-Plan")
    if report.event in {"firmware_installed", "firmware_confirmed"}:
        if not plan["firmware"] or report.firmwareVersion != plan["firmware"]["version"]:
            raise HTTPException(422, "Firmware gehört nicht zu diesem Update-Plan")
        if report.event == "firmware_confirmed":
            device.confirmed_firmware = device.firmware_version = report.firmwareVersion
    if report.event in {"boot_success", "sync_success"}:
        wanted = plan["desiredAssets"]
        inventory = report.installedAssets
        firmware = plan["firmware"]["version"] if plan["firmware"] else plan["initialFirmware"]
        if (inventory is None or any(inventory.get(key) != value for key, value in wanted.items())
                or report.firmwareVersion != firmware or plan["blockedAssets"]
                or (plan["firmware"] and device.confirmed_firmware != firmware)):
            raise HTTPException(409, "Erfolgreichen Start mit allen gewünschten Versionen und bestätigter Firmware melden")
        if report.event == "sync_success" and not db.scalar(select(SyncEvent.id).where(SyncEvent.run_id == run.id, SyncEvent.event == "boot_success")):
            raise HTTPException(409, "Zuerst boot_success bestätigen")
        # Never authorize deletion against a configuration that changed during download.
        if device.config_version != plan["configVersion"]:
            raise HTTPException(409, "Konfiguration geändert; bitte erneut synchronisieren")
        device.installed_assets = inventory
        device.firmware_version = firmware
        cleanup = [{"packageId": key, "version": value} for key, value in plan["previousAssets"].items() if wanted.get(key) != value]
    if report.event == "rollback":
        # Only explicitly reported rollback state replaces the inventory.
        if report.firmwareVersion is not None:
            device.firmware_version = report.firmwareVersion
        if report.installedAssets is not None:
            device.installed_assets = report.installedAssets
    run.status = report.event
    device.last_seen = datetime.now(timezone.utc)
    db.add(SyncEvent(run_id=run.id, event=report.event, details=report.model_dump(exclude_none=True)))
    db.commit()
    return {"ok": True, "cleanupAllowed": report.event in {"boot_success", "sync_success"}, "removeVersions": cleanup}
