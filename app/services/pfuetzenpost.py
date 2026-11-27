"""Server-authoritative Pfützenpost rooms. Mutations run on the ASGI event loop."""
import asyncio
import math
import secrets
import time
from dataclasses import dataclass, field

from app.services.game_status import GameMetric, GameParticipant, GameSession

LANES = 4
GOAL = 12
NO_SEAT = 255
TURN_SECONDS = 20
SETTLE_SECONDS = 1.2
RECONNECT_SECONDS = 30
LOBBY_SECONDS = 45
RESULT_SECONDS = 120
MAX_ROOMS = 128
NEUTRAL_NAMES = ("Mohn", "Klee", "Iris", "Mango")
NEUTRAL_COLORS = ("#ed786e", "#6bc582", "#9e92ee", "#ffbd61")


@dataclass
class Participant:
    id: str
    name: str
    color: str
    token: object = field(default_factory=object)
    disconnected: float | None = None
    sequence: int = 0


@dataclass(eq=False)
class Room:
    id: str
    deadline: float
    seats: dict[int, Participant] = field(default_factory=dict)
    retired: dict[int, tuple[str, str]] = field(default_factory=dict)
    phase: str = "lobby"
    positions: list[int] = field(default_factory=lambda: [0] * LANES)
    previous: list[int] = field(default_factory=lambda: [0] * LANES)
    dice: tuple[int, int] = (NO_SEAT, NO_SEAT)
    pending: tuple[int, int] | None = None
    active: int = NO_SEAT
    host: int = NO_SEAT
    round_pending: set[int] = field(default_factory=set)
    revision: int = 0
    move: int = 0
    turn_id: int = 0
    round: int = 0
    winners: int = 0
    reason: str = ""
    pause_remaining: float | None = None
    changed: asyncio.Event = field(default_factory=asyncio.Event)

    def publish(self):
        self.revision += 1
        self.changed.set()
        self.changed = asyncio.Event()

    def remaining_ms(self, now):
        if self.phase == "finished":
            return 0
        deadline = self.deadline
        if self.pause_remaining is not None:
            deadline = min(p.disconnected + RECONNECT_SECONDS for p in self.seats.values()
                           if p.disconnected is not None)
        return max(0, math.ceil((deadline - now) * 1000))

    def snapshot(self, seat, now):
        return {"type": "state", "schemaVersion": 1, "session": self.id, "revision": self.revision,
                "self": seat, "host": self.host, "turn": self.active,
                "phase": "paused" if self.pause_remaining is not None else self.phase,
                "remainingMs": self.remaining_ms(now), "move": self.move, "turnId": self.turn_id, "round": self.round,
                "positions": self.positions[:], "previous": self.previous[:], "dice": self.dice,
                "ack": self.seats[seat].sequence,
                "winners": self.winners, "reason": self.reason,
                "frogs": [self.frog(i) for i in range(LANES)]}

    def frog(self, i):
        player = self.seats.get(i)
        if player:
            return {"name": player.name, "color": player.color, "human": True,
                    "connected": player.disconnected is None}
        name, color = self.retired.get(i, (NEUTRAL_NAMES[i], NEUTRAL_COLORS[i]))
        return {"name": name, "color": color, "human": False, "connected": False}

    def finish(self, now, reason):
        self.phase, self.reason = "finished", reason
        self.active = NO_SEAT
        self.pause_remaining = None
        self.deadline = now + RESULT_SECONDS
        self.pending = None
        self.publish()

    def start(self, now, choose):
        seats = sorted(self.seats)
        self.active = seats[choose(len(seats))]
        self.round = 1
        self.round_pending = set(seats)
        self.phase = "ready"
        self.turn_id += 1
        self.deadline = now + TURN_SECONDS
        self.publish()

    def roll(self, choose):
        self.pending = (choose(LANES), choose(LANES))
        self.phase = "rolling"
        self.publish()

    def stop_dice(self, now):
        assert self.pending is not None
        self.dice, self.pending = self.pending, None
        self.previous = self.positions.copy()
        for i in self.dice:
            self.positions[i] = min(GOAL, self.positions[i] + 1)
            if self.positions[i] == GOAL:
                self.winners |= 1 << i
        self.move += 1
        self.round_pending.discard(self.active)
        self.phase = "settling"
        self.deadline = now + SETTLE_SECONDS
        self.publish()

    def next_turn(self, now):
        if not self.round_pending:
            if self.winners:
                self.finish(now, "delivered")
                return
            self.round_pending.update(self.seats)
            self.round += 1
        self.active = min(self.round_pending, key=lambda i: (i - self.active - 1) % LANES)
        self.phase = "ready"
        self.turn_id += 1
        self.deadline = now + TURN_SECONDS
        self.publish()


class PondService:
    def __init__(self, clock=time.monotonic, choose=secrets.randbelow):
        self.clock, self.choose = clock, choose
        self.rooms: dict[str, Room] = {}
        self.members: dict[str, tuple[Room, int]] = {}
        self.task: asyncio.Task | None = None

    def start(self):
        async def tick():
            while True:
                self.advance()
                await asyncio.sleep(0.1)
        self.task = asyncio.create_task(tick())

    async def stop(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        self.rooms.clear()
        self.members.clear()

    def _forget(self, room, seat):
        player = room.seats.pop(seat)
        if room.host == seat:
            room.host = min(room.seats, default=NO_SEAT)
        if room.phase != "lobby":
            room.retired[seat] = player.name, player.color
        if self.members.get(player.id) == (room, seat):
            del self.members[player.id]
        room.round_pending.discard(seat)

    def advance(self):
        now = self.clock()
        for room in list(self.rooms.values()):
            if room.phase == "finished":
                if now >= room.deadline:
                    for seat in list(room.seats):
                        self._forget(room, seat)
                    del self.rooms[room.id]
                    room.publish()
                continue
            for seat, player in list(room.seats.items()):
                if player.disconnected is not None and now >= player.disconnected + RECONNECT_SECONDS:
                    self._remove(room, seat, now)
            if room.phase == "finished" or room.pause_remaining is not None or now < room.deadline:
                continue
            if room.phase == "lobby":
                room.finish(now, "lobby_timeout")
            elif room.phase == "settling":
                room.next_turn(now)
            else:
                # An idle turn still contributes two random dice to the shared race.
                if room.phase == "ready":
                    room.roll(self.choose)
                room.stop_dice(now)

    def join(self, device_id, name, color, session):
        self.advance()
        now = self.clock()
        existing = self.members.get(device_id)
        if session:
            if not existing or existing[0].id != session:
                raise ValueError("session_lost")
            room, seat = existing
        elif existing and existing[0].phase != "finished":
            room, seat = existing
        else:
            if existing:
                old_room, old_seat = existing
                self._forget(old_room, old_seat)
                old_room.publish()
            room = next((r for r in self.rooms.values() if r.phase == "lobby" and len(r.seats) < LANES
                         and any(p.disconnected is None for p in r.seats.values())), None)
            if room is None:
                if len(self.rooms) >= MAX_ROOMS:
                    raise ValueError("server_busy")
                room = Room(secrets.token_hex(16), now + LOBBY_SECONDS)
                self.rooms[room.id] = room
            seat = next(i for i in range(LANES) if i not in room.seats)
            room.seats[seat] = Participant(device_id, name, color)
            if room.host == NO_SEAT:
                room.host = seat
            self.members[device_id] = room, seat
        player = room.seats[seat]
        player.token = object()
        player.disconnected = None
        self._resume(room, now)
        room.publish()
        return room, seat, player.token

    @staticmethod
    def owns(room, seat, token):
        player = room.seats.get(seat)
        return player is not None and player.token is token and player.disconnected is None

    @staticmethod
    def _resume(room, now):
        if room.pause_remaining is not None and all(p.disconnected is None for p in room.seats.values()):
            room.deadline = now + room.pause_remaining
            room.pause_remaining = None

    def disconnect(self, room, seat, token):
        self.advance()
        if not self.owns(room, seat, token):
            return
        now = self.clock()
        if room.phase not in ("lobby", "finished") and room.pause_remaining is None:
            room.pause_remaining = max(0, room.deadline - now)
        room.seats[seat].disconnected = now
        room.publish()

    def _remove(self, room, seat, now):
        self._forget(room, seat)
        if room.phase == "finished":
            room.publish()
        elif not room.seats or (room.phase != "lobby" and len(room.seats) < 2):
            room.finish(now, "players_left")
        elif room.phase != "lobby" and seat == room.active and room.phase != "settling":
            room.pending = None
            room.next_turn(now)
            if room.phase != "finished" and room.pause_remaining is not None:
                room.pause_remaining = TURN_SECONDS
            self._resume(room, now)
            room.publish()
        else:
            self._resume(room, now)
            room.publish()

    def message(self, room, seat, token, frame):
        self.advance()
        if not self.owns(room, seat, token):
            return False
        if not isinstance(frame, dict):
            raise ValueError("invalid_message")
        kind = frame.get("type")
        now = self.clock()
        if kind == "leave":
            self._remove(room, seat, now)
            return False
        if kind == "ping":
            return True
        if kind not in ("start", "roll", "stop"):
            raise ValueError("invalid_message")
        seq, turn_id = frame.get("seq"), frame.get("turnId")
        player = room.seats[seat]
        if (type(seq) is not int or not player.sequence < seq <= 0xffffffff or
                type(turn_id) is not int or turn_id != room.turn_id):
            return True
        if kind == "start" and room.phase == "lobby" and seat == room.host and len(room.seats) >= 2:
            if all(p.disconnected is None for p in room.seats.values()):
                player.sequence = seq
                room.start(now, self.choose)
        elif seat == room.active and room.pause_remaining is None:
            if kind == "roll" and room.phase == "ready":
                player.sequence = seq
                room.roll(self.choose)
            elif kind == "stop" and room.phase == "rolling":
                player.sequence = seq
                room.stop_dice(now)
        return True

    def status(self):
        now = self.clock()
        return tuple(GameSession(session_id=room.id,
                                 phase="paused" if room.pause_remaining is not None else room.phase,
                                 label="Warte auf WLAN" if room.pause_remaining is not None else
                                 {"lobby": "Mitspieler gesucht", "ready": "Spiel läuft", "rolling": "Würfel laufen",
                                  "settling": "Frösche ziehen", "finished": "Partie beendet"}[room.phase],
                                 activity={"lobby": "waiting", "finished": "finished"}.get(room.phase, "running"),
                                 remaining_ms=room.remaining_ms(now), max_players=LANES,
                                 players=tuple(GameParticipant(p.id, p.disconnected is None) for p in room.seats.values()),
                                 metrics=(GameMetric("Runde", room.round), GameMetric("Züge", room.move)))
                     for room in self.rooms.values())
