"""Single-process LAN game coordinator; bounded queues isolate slow receivers."""
import asyncio
from contextlib import suppress
import time
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from app.api.routes import device_or_404
from app.core.database import get_db
from app.services.snake import Room

router = APIRouter(prefix="/api/v1/devices")


def now_ms():
    return time.monotonic_ns() // 1_000_000


class SnakeHub:
    def __init__(self):
        self.room = None
        self.connections = {}
        self.task = None

    def start(self):
        self.room = None
        self.connections = {}
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
        self.connections.clear()
        self.room = None

    @staticmethod
    def deliver(queue, state):
        if queue.full():
            queue.get_nowait()  # Every message is a complete replacement state.
        queue.put_nowait(state)

    def broadcast(self):
        if not self.room:
            return
        state = self.room.snapshot(now_ms())
        for queue in self.connections.values():
            self.deliver(queue, state)

    def join(self, metadata, session):
        now = now_ms()
        if session and (not self.room or self.room.id != session or metadata[0] not in self.room.players):
            raise ValueError("Homeserver neu gestartet oder Partie beendet. Bitte neu starten.")
        if not session and (not self.room or self.room.ended):
            self.room = Room(now)
        self.room.join(*metadata, now)
        old = self.connections.get(metadata[0])
        if old:
            if old.full():
                old.get_nowait()
            old.put_nowait({"type":"error", "detail":"Gerät bereits verbunden"})
        queue = asyncio.Queue(maxsize=1)
        self.connections[metadata[0]] = queue
        self.broadcast()
        return queue

    def status(self):
        from app.services.game_status import GameMetric, GameParticipant, GameSession
        from app.services.snake import COLUMNS, ROWS
        room = self.room
        if room is None:
            return ()
        now = now_ms()
        labels = {"lobby": "Mitspieler werden gesucht", "countdown": "Startcountdown",
                  "playing": "Spiel läuft", "alone": "Keine Mitspieler gefunden", "finished": "Partie beendet"}
        activity = "running" if room.phase == "playing" else "waiting" if room.phase in {"lobby", "countdown"} else "finished"
        return (GameSession(
            session_id=room.id, phase=room.phase, label=labels[room.phase], activity=activity,
            remaining_ms=room.remaining_ms(now),
            players=tuple(GameParticipant(p.id, p.connected) for p in room.players.values()), max_players=4,
            metrics=(GameMetric("Teampunkte", room.score), GameMetric("Punkteziel", room.target),
                     GameMetric("Spielfeld", f"{COLUMNS} × {ROWS}"))),)

    async def run(self):
        while True:
            await asyncio.sleep(.05)
            if self.room:
                before = self.room.revision
                self.room.advance(now_ms())
                if before != self.room.revision:
                    self.broadcast()
                # Keep terminal state for reconnects, with bounded retention.
                if self.room.ended and now_ms()-self.room.ended > 180_000:
                    self.room = None


hub = SnakeHub()


@router.websocket("/{device_id}/snake/ws")
async def snake_socket(websocket: WebSocket, device_id: str, db: Session = Depends(get_db)):
    bind = db.get_bind()
    def metadata():
        with Session(bind) as session:
            d = device_or_404(device_id, session)
            if "snake" not in d.enabled_games or not any(p.page_id == "games" and p.enabled for p in d.pages):
                raise HTTPException(403, "Snake ist für dieses Gerät ausgeschaltet")
            return d.device_id, d.avatar if d.avatar.startswith("avatar-") else "avatar-"+d.avatar, d.accent_color
    try:
        player = await run_in_threadpool(metadata)
    except HTTPException as error:
        await websocket.close(code=1008, reason=str(error.detail))
        return
    await websocket.accept()
    queue = None
    writer = None
    room = None
    async def send_states():
        while True:
            state = await queue.get()
            await asyncio.wait_for(websocket.send_json(state), 2)
            if state["type"] == "error":
                await websocket.close(code=1008)
                return
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), 5)
        import json
        if len(raw) > 512:
            raise ValueError("Nachricht zu groß")
        frame = json.loads(raw)
        if (not isinstance(frame, dict) or frame.get("type") != "join" or
                not isinstance(frame.get("session", ""), str) or len(frame.get("session", "")) > 32):
            raise ValueError("Ungültiger Beitritt")
        if type(frame.get("protocolVersion")) is not int or frame["protocolVersion"] != 2:
            raise ValueError("Bitte die Geräte-Firmware auf Version 1.4.0 oder neuer aktualisieren.")
        queue = hub.join(player, frame.get("session", ""))
        room = hub.room
        writer = asyncio.create_task(send_states())
        while True:
            raw = await asyncio.wait_for(websocket.receive_text(), 5)
            if writer.done():
                writer.result()
                return
            if len(raw) > 512:
                raise ValueError("Nachricht zu groß")
            frame = json.loads(raw)
            if not isinstance(frame, dict) or frame.get("type") not in {"input", "sync", "ping", "leave"}:
                raise ValueError("Ungültige Nachricht")
            if hub.connections.get(device_id) is not queue or hub.room is not room:
                raise ValueError("Partie beendet. Bitte neu starten.")
            room.advance(now_ms())
            if frame["type"] == "leave":
                return
            room.input(device_id, frame, now_ms())
            if frame["type"] == "input":
                hub.broadcast()
            else:
                hub.deliver(queue, room.snapshot(now_ms()))
    except (ValueError, KeyError, TypeError) as error:
        with suppress(RuntimeError, WebSocketDisconnect):
            await websocket.send_json({"type":"error", "detail":str(error)[:160]})
    except (WebSocketDisconnect, RuntimeError, asyncio.TimeoutError):
        pass
    finally:
        if writer:
            writer.cancel()
            with suppress(asyncio.CancelledError, RuntimeError, WebSocketDisconnect, asyncio.TimeoutError):
                await writer
        if queue and hub.connections.get(device_id) is queue:
            hub.connections.pop(device_id, None)
            if room:
                room.disconnect(device_id, now_ms())
                hub.broadcast()
        with suppress(RuntimeError, WebSocketDisconnect):
            await websocket.close()
