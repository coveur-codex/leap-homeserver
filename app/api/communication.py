"""Device chat relay. All names, text and symbols come from server-owned data."""
import asyncio
import json
from datetime import timezone
from threading import Lock
from contextlib import suppress

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from starlette.concurrency import run_in_threadpool
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
    relay_hub.publish()
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


class RelayHub:
    """Wake subscribers after commit, including HTTP sends from worker threads."""
    def __init__(self):
        self.lock = Lock()
        self.listeners = set()

    def register(self):
        listener = (asyncio.get_running_loop(), asyncio.Event())
        with self.lock:
            self.listeners.add(listener)
        return listener

    def remove(self, listener):
        with self.lock:
            self.listeners.discard(listener)

    def publish(self):
        with self.lock:
            for loop, event in self.listeners:
                if not loop.is_closed():
                    loop.call_soon_threadsafe(event.set)


relay_hub = RelayHub()


@router.websocket("/{device_id}/communication/ws")
async def communication_socket(websocket: WebSocket, device_id: str, db: Session = Depends(get_db)):
    # Never hold a DB transaction across a socket wait. Each operation gets a
    # short-lived session; synchronous SQLite work stays off the event loop.
    bind = db.get_bind()

    def operation(action, *args):
        with Session(bind) as session:
            return action(device_id, *args, db=session)

    def check(device_id, db):
        participant(device_id, db)

    try:
        await run_in_threadpool(operation, check)
    except HTTPException as error:
        await websocket.close(code=1008, reason=str(error.detail))
        return
    await websocket.accept()
    listener = relay_hub.register()  # Register before reading initial history.
    wake = listener[1]
    receiver = asyncio.create_task(websocket.receive_json())
    waiter = None
    subscribed, inflight, cursor = False, False, None
    try:
        while True:
            waiter = asyncio.create_task(wake.wait())
            done, _ = await asyncio.wait((receiver, waiter), timeout=30,
                                         return_when=asyncio.FIRST_COMPLETED)
            waiter.cancel()
            with suppress(asyncio.CancelledError):
                await waiter
            waiter = None
            changed = wake.is_set()
            wake.clear()
            # Also checks permissions/other-process commits every 30 seconds.
            await run_in_threadpool(operation, check)
            fetch = not done or changed
            force = False
            if receiver in done:
                frame = receiver.result()
                receiver = asyncio.create_task(websocket.receive_json())
                if not isinstance(frame, dict):
                    await websocket.close(code=1008, reason="Ungültige Nachricht")
                    return
                if len(json.dumps(frame)) > 1024:
                    await websocket.close(code=1008, reason="Nachricht zu groß")
                    return
                kind = frame.get("type")
                if kind == "sync":
                    value = frame.get("since")
                    if value is not None and (type(value) is not int or not 0 <= value <= 9223372036854775807):
                        await websocket.close(code=1008, reason="Ungültiger Cursor")
                        return
                    if inflight and value != cursor:
                        await websocket.close(code=1008, reason="Cursor nicht bestätigt")
                        return
                    force = not subscribed
                    subscribed, inflight, cursor, fetch = True, False, value, True
                elif kind == "send":
                    try:
                        body = RelaySend.model_validate({k: v for k, v in frame.items() if k != "type"})
                        result = await run_in_threadpool(operation, send_message, body)
                        await websocket.send_json(jsonable_encoder({"type": "ack", **result}))
                        fetch = True
                    except HTTPException as error:
                        await websocket.send_json({"type": "error", "eventId": frame.get("eventId"),
                                                   "status": error.status_code, "detail": str(error.detail)})
                    except ValueError:
                        await websocket.send_json({"type": "error", "eventId": frame.get("eventId"), "status": 422})
                elif kind == "ping":
                    await websocket.send_json({"type": "pong"})
                else:
                    await websocket.close(code=1008, reason="Unbekannter Nachrichtentyp")
                    return
            if subscribed and not inflight and fetch:
                page = await run_in_threadpool(operation, receive_messages, cursor)
                if force or page["messages"] or page["reset"]:
                    cursor, inflight = page["cursor"], True
                    await websocket.send_json(jsonable_encoder({"type": "messages", **page}))
    except HTTPException as error:
        await websocket.close(code=1008, reason=str(error.detail))
    except (WebSocketDisconnect, RuntimeError):
        pass
    except (ValueError, KeyError, TypeError):
        await websocket.close(code=1008, reason="Ungültiges JSON")
    finally:
        relay_hub.remove(listener)
        receiver.cancel()
        if waiter:
            waiter.cancel()
        with suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError, ValueError, KeyError, TypeError):
            await receiver
