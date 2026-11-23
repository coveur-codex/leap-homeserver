"""One authoritative freight yard; all mutations run on the ASGI event loop."""
import asyncio
from dataclasses import dataclass
import secrets
import time
from contextlib import suppress

from app.services.game_status import GameMetric, GameParticipant, GameSession
from app.services.rangierwerk_native import ENGINES, STEP_MS, Yard

CARD_MS = 600_000
SUMMARY_MS = 3000
DRIVE_MS = 450
PRESENCE_MS = 3500
RESERVATION_MS = 60_000
LEVELS = ("Kleiner Bahnhof", "Rangiermeister", "Güterbahnhof", "Großer Rangierbahnhof")


@dataclass
class Player:
    device_id: str
    slot: int
    accent: str
    name: str
    token: object
    seen_at: int
    disconnected_at: int | None = None
    direction: int = 0
    drive_until: int = 0
    next_step: int = 0
    sequence: int = 0
    rescued_at: int | None = None

    @property
    def connected(self):
        return self.disconnected_at is None


class YardService:
    def __init__(self, difficulty=1, clock=None, seed=None, generation=None):
        self.clock = clock or (lambda: time.monotonic_ns() // 1_000_000)
        self.seed_factory = seed or (lambda: secrets.randbits(32))
        self.generation = generation or (secrets.randbits(31) + 1)
        self.next_difficulty = difficulty
        self.players = {}
        self.last = self.clock()
        self.yard = Yard()
        self.task = None
        self.cached_at = None
        self._new_card()

    def _new_card(self):
        self.seed = self.seed_factory()
        self.difficulty = self.next_difficulty
        self.remaining, self.summary = CARD_MS, 0
        self.yard.reset(self.seed, self.difficulty)
        for player in self.players.values():
            self.yard.join(player.slot)
            player.direction, player.next_step, player.rescued_at = 0, self.last, None
        self._order_count()
        self.cached_at = None

    def _order_count(self):
        self.yard.order_count(4 if sum(p.connected for p in self.players.values()) == ENGINES else 3)

    def advance(self):
        now = self.clock()
        active_until = max((p.seen_at + PRESENCE_MS for p in self.players.values() if p.connected),
                           default=self.last)
        elapsed = max(0, min(now, active_until) - self.last)
        self.last = now
        for player in list(self.players.values()):
            if player.connected and now >= player.seen_at + PRESENCE_MS:
                player.direction = 0
                player.disconnected_at = player.seen_at + PRESENCE_MS
                self._order_count()
                self.cached_at = None
            if not player.connected and now - player.disconnected_at >= RESERVATION_MS:
                self._remove(player)

        if self.summary:
            if elapsed >= self.summary:
                self.generation = (self.generation % 0xffffffff) + 1
                self._new_card()
            else:
                self.summary -= elapsed
            return

        if elapsed >= self.remaining:
            self.summary = SUMMARY_MS
            self.remaining = 0
            for player in self.players.values():
                player.direction = 0
            return

        self.remaining -= elapsed
        if elapsed:
            self.yard.tick(elapsed)
            self.cached_at = None
        for player in self.players.values():
            if player.direction and now >= player.drive_until:
                player.direction = 0
            if player.connected and player.direction and now >= player.next_step:
                self.yard.drive(player.slot, player.direction)
                player.next_step = now + STEP_MS
                self.cached_at = None

    def join(self, device_id, accent, name):
        self.advance()
        player = self.players.get(device_id)
        now = self.last
        if player is None:
            taken = {p.slot for p in self.players.values()}
            slot = next((i for i in range(ENGINES) if i not in taken), None)
            if slot is None:
                return None
            if not self.yard.join(slot):
                raise RuntimeError("Rangierwerk depot unavailable")
            player = Player(device_id, slot, accent, name, object(), now)
            self.players[device_id] = player
        else:
            player.token = object()
            player.seen_at = now
            player.accent, player.name = accent, name
            player.disconnected_at = None
            player.direction = 0
            player.sequence = 0
        self._order_count()
        self.cached_at = None
        return player

    def current(self, player, token):
        return player.connected and player.token is token and self.players.get(player.device_id) is player

    def disconnect(self, player, token):
        self.advance()
        if self.current(player, token):
            player.direction = 0
            player.disconnected_at = self.last
            self._order_count()

    def _remove(self, player):
        self.yard.leave(player.slot)
        del self.players[player.device_id]
        self._order_count()
        self.cached_at = None

    def message(self, player, token, frame):
        self.advance()
        if not self.current(player, token):
            return False
        if not isinstance(frame, dict):
            raise ValueError("invalid_message")
        action = frame.get("type")
        if action == "leave":
            self._remove(player)
            return False
        if action == "ping":
            player.seen_at = self.last
            return True
        if action not in ("drive", "turnout", "split", "recover"):
            raise ValueError("invalid_message")
        seq, card = frame.get("seq"), frame.get("card")
        if type(seq) is not int or not 0 < seq <= 0xffffffff or type(card) is not int:
            raise ValueError("invalid_sequence")
        if seq <= player.sequence or card != self.generation:
            return True
        player.sequence = seq
        player.seen_at = self.last
        if self.summary:
            return True
        if action == "drive":
            direction = frame.get("direction")
            if type(direction) is not int or direction not in (-1, 0, 1):
                raise ValueError("invalid_direction")
            player.direction = direction
            player.drive_until = self.last + DRIVE_MS
        elif action == "turnout":
            index = frame.get("index")
            if type(index) is not int or not 0 <= index < 32:
                raise ValueError("invalid_turnout")
            self.yard.turnout(index)
        elif not player.direction:
            if action == "split":
                a, b = frame.get("a"), frame.get("b")
                if any(type(n) is not int or not 0 < n <= 0xffffffff for n in (a, b)):
                    raise ValueError("invalid_coupling")
                self.yard.split(player.slot, a, b)
            elif player.rescued_at is None or self.last - player.rescued_at >= 5000:
                if self.yard.recover(player.slot):
                    player.rescued_at = self.last
        self.cached_at = None
        return True

    def state(self):
        # At most four sockets read the same state several times per tick.
        if self.cached_at != self.last:
            self.cached_state = self.yard.snapshot()
            self.cached_at = self.last
        return self.cached_state

    def snapshot(self, player):
        return {"type": "state", "protocolVersion": 1, "card": self.generation,
                "seed": self.seed, "difficulty": self.difficulty, "remainingMs": self.remaining,
                "summary": bool(self.summary), "self": player.slot,
                "colors": [[p.slot, p.accent, p.name, p.connected] for p in self.players.values()], **self.state()}

    def status(self):
        self.advance()
        state = self.state()
        active = any(p.connected for p in self.players.values())
        label = "Kartenwechsel" if self.summary else "Rangierbetrieb" if active else "Bahnhof pausiert"
        phase = "summary" if self.summary else "playing" if active else "paused"
        return (GameSession(str(self.generation), phase, label, "running" if active else "idle",
            self.remaining, tuple(GameParticipant(p.device_id, p.connected) for p in self.players.values()),
            ENGINES, (GameMetric("Schwierigkeit", LEVELS[self.difficulty - 1]),
                      GameMetric("Nächste Karte", LEVELS[self.next_difficulty - 1]),
                      GameMetric("Offene Aufträge", len(state["orders"])),
                      GameMetric("Gelieferte Wagen", state["delivered"]),
                      GameMetric("Kartenseed", self.seed))),)

    def start(self):
        async def run():
            while True:
                self.advance()
                await asyncio.sleep(0.04)
        self.task = asyncio.create_task(run())

    async def stop(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
        self.yard.close()
