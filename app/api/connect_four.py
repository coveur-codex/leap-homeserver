"""Device WebSocket transport; the matchmaker never trusts client identities/colors."""
import asyncio
import json
from contextlib import suppress

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.models import Device
from app.services.connect_four import matchmaker

router = APIRouter()


def identity(bind, device_id):
    with Session(bind) as db:
        device = db.scalar(select(Device).where(Device.device_id == device_id, Device.enabled == True))
        if not device or not any(p.page_id == "games" and p.enabled for p in device.pages):
            raise ValueError("game_disabled")
        if "connect_four" not in device.enabled_games:
            raise ValueError("game_disabled")
        name = (device.child_name or device.name).encode("utf-8")[:96].decode("utf-8", errors="ignore")
        return device.device_id, name, device.accent_color


@router.websocket("/api/v1/devices/{device_id}/connect-four/ws")
async def game_socket(ws: WebSocket, device_id: str, db: Session = Depends(get_db)):
    bind = db.get_bind()
    await ws.accept()
    match = player = token = None
    try:
        who = await run_in_threadpool(identity, bind, device_id)
        raw = await asyncio.wait_for(ws.receive_text(), 5)
        frame = json.loads(raw) if len(raw) <= 512 else None
        if (not isinstance(frame, dict) or frame.get("type") != "join" or
                type(frame.get("protocolVersion")) is not int or frame["protocolVersion"] != 1 or
                not isinstance(frame.get("session"), str) or len(frame["session"]) not in (0, 32)):
            raise ValueError("invalid_join")
        match, player, token = matchmaker.join(*who, frame["session"])
        # One writer, bounded sends. Each message is a complete authoritative state.
        async def send_states():
            while True:
                matchmaker.advance()
                if player.token != token or matchmaker.members.get(player.id) != match.session:
                    return
                await asyncio.wait_for(ws.send_json(match.snapshot(matchmaker.clock())), 2)
                await asyncio.sleep(0.25)

        async def receive_inputs():
            while True:
                raw = await asyncio.wait_for(ws.receive_text(), 5)
                if len(raw) > 512:
                    raise ValueError("message_too_large")
                await run_in_threadpool(identity, bind, device_id)
                matchmaker.message(match, player, token, json.loads(raw))
                if player.left:
                    return

        sender = asyncio.create_task(send_states())
        receiver = asyncio.create_task(receive_inputs())
        try:
            done, _ = await asyncio.wait((sender, receiver), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            for task in (sender, receiver):
                task.cancel()
            await asyncio.gather(sender, receiver, return_exceptions=True)
    except (ValueError, KeyError, TypeError, asyncio.TimeoutError) as exc:
        if str(exc) != "reconnect_required":
            with suppress(Exception):
                await asyncio.wait_for(ws.send_json({"type": "error", "code": str(exc) or "timeout"}), 2)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        if match is not None:
            matchmaker.leave(match, player, token)
        with suppress(Exception):
            await ws.close()
