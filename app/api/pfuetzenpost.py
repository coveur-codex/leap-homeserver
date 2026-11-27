"""Device WebSocket with event-driven snapshots and a single writer per connection."""
import asyncio
import json
from contextlib import suppress

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.models import Device

router = APIRouter()


def identity(bind, device_id):
    with Session(bind) as db:
        device = db.scalar(select(Device).where(Device.device_id == device_id, Device.enabled == True))
        if (not device or "pfuetzenpost" not in device.enabled_games or
                not any(p.page_id == "games" and p.enabled for p in device.pages)):
            raise ValueError("game_disabled")
        name = " ".join((device.child_name or device.name).split()) or "LEAP"
        name = name.encode("utf-8")[:32].decode("utf-8", errors="ignore")
        return device.device_id, name, device.accent_color


async def receive_json(ws, timeout):
    raw = await asyncio.wait_for(ws.receive_text(), timeout)
    if len(raw) > 512:
        raise ValueError("message_too_large")
    return json.loads(raw)


@router.websocket("/api/v1/devices/{device_id}/pfuetzenpost/ws")
async def pond_socket(ws: WebSocket, device_id: str, db: Session = Depends(get_db)):
    hub = ws.app.state.pfuetzenpost
    bind = db.get_bind()
    await ws.accept()
    room = None
    try:
        who = await run_in_threadpool(identity, bind, device_id)
        frame = await receive_json(ws, 5)
        if (not isinstance(frame, dict) or frame.get("type") != "join" or
                type(frame.get("protocolVersion")) is not int or frame["protocolVersion"] != 1 or
                not isinstance(frame.get("session"), str) or len(frame["session"]) not in (0, 32)):
            raise ValueError("invalid_join")
        room, seat, token = hub.join(*who, frame["session"])

        async def send_states():
            while hub.owns(room, seat, token):
                changed = room.changed
                await asyncio.wait_for(ws.send_json(room.snapshot(seat, hub.clock())), 2)
                while not changed.is_set():
                    try:
                        await asyncio.wait_for(changed.wait(), 5)
                    except asyncio.TimeoutError:
                        await asyncio.wait_for(ws.send_json({"type": "pong"}), 2)

        async def receive_inputs():
            while True:
                message = await receive_json(ws, 14)
                await run_in_threadpool(identity, bind, device_id)
                if not hub.message(room, seat, token, message):
                    return

        tasks = (asyncio.create_task(send_states()), asyncio.create_task(receive_inputs()))
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    except (ValueError, TypeError, KeyError, asyncio.TimeoutError) as exc:
        with suppress(Exception):
            await asyncio.wait_for(ws.send_json({"type": "error", "code": str(exc) or "timeout"}), 2)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        if room is not None:
            hub.disconnect(room, seat, token)
        with suppress(Exception):
            await ws.close()
