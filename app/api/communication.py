"""Device chat relay. All names, text and symbols come from server-owned data."""
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.routes import device_or_404
from app.core.database import get_db
from app.models import CommunicationMessage, CommunicationRelayEvent
from app.services.communication_icons import ICONS

router = APIRouter(prefix="/api/v1/devices")


class RelaySend(BaseModel):
    model_config = ConfigDict(extra="forbid")
    eventId: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    templateId: str = Field(min_length=1, max_length=36)


def participant(device_id, db):
    device = device_or_404(device_id, db)
    if not device.communication_enabled:
        raise HTTPException(403, "Kommunikation ist für dieses Gerät ausgeschaltet")
    return device


def snapshot(event):
    return {"id": event.id, "eventId": event.event_id, "senderId": event.sender_id,
            "name": event.name, "text": event.text, "symbol": event.symbol,
            "sentAt": event.sent_at.replace(tzinfo=timezone.utc) if event.sent_at.tzinfo is None else event.sent_at}


@router.post("/{device_id}/communication/messages")
def send_message(device_id: str, body: RelaySend, db: Session = Depends(get_db)):
    device = participant(device_id, db)
    existing_query = select(CommunicationRelayEvent).where(
        CommunicationRelayEvent.sender_id == device_id,
        CommunicationRelayEvent.event_id == body.eventId)
    existing = db.scalar(existing_query)
    if existing:
        if existing.template_id != body.templateId:
            raise HTTPException(409, "Nachrichtenkennung wird bereits verwendet")
        return {"ok": True, "eventId": body.eventId, "message": snapshot(existing)}
    if body.templateId in ICONS:
        text, symbol = "", ICONS[body.templateId]["symbol"]
    else:
        template = db.get(CommunicationMessage, body.templateId)
        if template is None or not template.active:
            raise HTTPException(422, "Nachrichtenvorlage oder Icon ist nicht aktiv")
        text, symbol = template.text, template.symbol
    event = CommunicationRelayEvent(sender_id=device_id, event_id=body.eventId,
        template_id=body.templateId, name=device.avatar_name or device.name,
        text=text, symbol=symbol)
    db.add(event)
    try:
        db.commit()
    except IntegrityError:
        # Concurrent retries of the same request must share the same event.
        db.rollback()
        event = db.scalar(existing_query)
        if event is None:
            raise
        if event.template_id != body.templateId:
            raise HTTPException(409, "Nachrichtenkennung wird bereits verwendet")
    return {"ok": True, "eventId": body.eventId, "message": snapshot(event)}


@router.get("/{device_id}/communication/messages")
def receive_messages(device_id: str, since: int | None = Query(None, ge=0, le=9223372036854775807),
                     db: Session = Depends(get_db)):
    participant(device_id, db)
    latest = db.scalar(select(func.max(CommunicationRelayEvent.id))) or 0
    reset = since is not None and since > latest
    if since is None or reset:
        # Seed the visible history on boot without ringing for old messages.
        rows = list(reversed(db.scalars(select(CommunicationRelayEvent).where(
            CommunicationRelayEvent.id <= latest).order_by(CommunicationRelayEvent.id.desc()).limit(8)).all()))
        cursor, more = latest, False
    else:
        rows = db.scalars(select(CommunicationRelayEvent).where(
            CommunicationRelayEvent.id > since, CommunicationRelayEvent.id <= latest)
            .order_by(CommunicationRelayEvent.id).limit(8)).all()
        cursor = rows[-1].id if rows else latest
        more = cursor < latest
    return {"schemaVersion": 1, "messages": [snapshot(row) for row in rows],
            "cursor": cursor, "more": more, "reset": reset}
