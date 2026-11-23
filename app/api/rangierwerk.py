"""Device connections use the same grants and configured accents as Snake."""
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
        device = db.scalar(select(Device).where(Device.device_id == device_id, Device.enabled.is_(True)))
        if (not device or "rangierwerk" not in device.enabled_games or
                not any(p.page_id == "games" and p.enabled for p in device.pages)):
            raise ValueError("game_disabled")
        name = (device.child_name or device.name or device.device_id).encode("utf-8")[:20].decode("utf-8", errors="ignore")
        return device.accent_color, name


async def receive(ws):
    raw = await asyncio.wait_for(ws.receive_text(), 5)
    if len(raw) > 512:
        raise ValueError("message_too_large")
    return json.loads(raw)


@router.websocket("/api/v1/devices/{device_id}/rangierwerk/ws")
async def socket(ws: WebSocket, device_id: str, db: Session = Depends(get_db)):
    hub = ws.app.state.rangierwerk
    bind = db.get_bind()
    await ws.accept()
    player = token = None
    try:
        accent, name = await run_in_threadpool(identity, bind, device_id)
        join = await receive(ws)
        if (not isinstance(join, dict) or join.get("type") != "join" or
                type(join.get("protocolVersion")) is not int or join["protocolVersion"] != 1):
            raise ValueError("invalid_join")
        player = hub.join(device_id, accent, name)
        if player is None:
            await asyncio.wait_for(ws.send_json({"type": "full"}), 2)
            return
        token = player.token

        async def send_states():
            while hub.current(player, token):
                await asyncio.wait_for(ws.send_json(hub.snapshot(player)), 2)
                await asyncio.sleep(0.12)

        async def inputs():
            checked = hub.clock()
            while True:
                frame = await receive(ws)
                if hub.clock() - checked >= 2000:
                    accent, name = await run_in_threadpool(identity, bind, device_id)
                    if hub.current(player, token):
                        player.accent, player.name = accent, name
                    checked = hub.clock()
                if not hub.message(player, token, frame):
                    return

        tasks = (asyncio.create_task(send_states()), asyncio.create_task(inputs()))
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
        if player is not None:
            hub.disconnect(player, token)
        with suppress(Exception):
            await ws.close()
