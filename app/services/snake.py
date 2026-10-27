"""Bounded, in-memory cooperative Snake. All mutations run on one asyncio loop.

Integer monotonic milliseconds and simultaneous proposals make time and collisions
independent of connection order. No device performs simulation.
"""
from dataclasses import dataclass, field
from collections import deque
import random
import secrets

COLUMNS, ROWS, STEP = 40, 13, 450
LOBBY, COUNTDOWN, DURATION = 10_000, 3_000, 120_000
RESPAWN, PROTECTION, STALE, REMOVE = 3_000, 900, 3_000, 15_000
DIRECTIONS = ((0, -1), (0, 1), (-1, 0), (1, 0))


@dataclass
class Player:
    id: str
    avatar: str
    accent: str
    body: list = field(default_factory=list)
    direction: int = 3
    queued: int | None = None
    seq: int = 0
    connected: bool = True
    seen: int = 0
    respawn: int = 0
    protected: int = 0


class Room:
    def __init__(self, now, rng=None):
        self.id = secrets.token_hex(16)
        self.created = now
        self.phase = "lobby"
        self.players = {}
        self.score = self.tick = self.revision = 0
        self.target = self.food_count = 0
        self.food = set()
        self.start = now + LOBBY + COUNTDOWN
        self.next_step = self.start + STEP
        self.ended = 0
        self.rng = rng or random.Random()

    def join(self, id, avatar, accent, now):
        self.advance(now)
        if id in self.players:
            p = self.players[id]
            p.connected, p.seen = True, now
            self.revision += 1
            return p
        if self.phase != "lobby" or len(self.players) >= 4:
            raise ValueError("Diese Partie ist bereits gestartet oder voll")
        p = Player(id, avatar, accent, seen=now)
        self.players[id] = p
        self.revision += 1
        return p

    def disconnect(self, id, now):
        p = self.players.get(id)
        if p:
            p.connected = False
            p.seen = min(p.seen, now)
            p.queued = None
            self.revision += 1

    def input(self, id, frame, now):
        p = self.players[id]
        p.seen, p.connected = now, True
        if frame.get("type") != "input":
            return
        seq, tick, direction = (frame.get(k) for k in ("seq", "tick", "direction"))
        if (type(seq) is not int or not 0 < seq <= 2**32-1 or
                type(tick) is not int or type(direction) is not int or direction not in range(4)):
            raise ValueError("Ungültige Steuerung")
        if seq <= p.seq:
            return
        p.seq = seq
        # One buffered turn; delayed/replayed inputs never steer a future move.
        if (self.phase == "playing" and self.tick <= tick <= self.tick + 1 and
                p.queued is None and direction != (p.direction ^ 1)):
            p.queued = direction

    def spawn(self, p, now):
        occupied = self.food | {cell for other in self.players.values() for cell in other.body}
        # Need a free body AND two forward cells. Retry next step if crowded.
        preferred = 1 + list(self.players).index(p.id) * 3
        for y in sorted(range(1, ROWS-1), key=lambda y: (abs(y-preferred), y)):
            for x in range(2, COLUMNS-2):
                cells = [(x-i, y) for i in range(3)]
                if not occupied.intersection(cells + [(x+1,y), (x+2,y)]):
                    p.body, p.direction, p.queued = cells, 3, None
                    p.respawn, p.protected = 0, now + PROTECTION
                    return
        p.respawn = now + STEP

    def refill(self):
        occupied = {cell for p in self.players.values() for cell in p.body}
        # Flood free space from every living head; don't place inside sealed bodies.
        seen, queue = set(), deque()
        for p in self.players.values():
            if p.body:
                queue.append(p.body[0])
        while queue:
            x, y = queue.popleft()
            for dx, dy in DIRECTIONS:
                cell = x+dx, y+dy
                if (0 <= cell[0] < COLUMNS and 0 <= cell[1] < ROWS and
                        cell not in occupied and cell not in seen):
                    seen.add(cell)
                    queue.append(cell)
        free = sorted(seen - self.food)
        while free and len(self.food) < self.food_count:
            self.food.add(free.pop(self.rng.randrange(len(free))))

    def move(self, now):
        self.tick += 1
        proposals, dead, stopped = {}, set(), set()
        for p in self.players.values():
            if now - p.seen >= STALE:
                p.connected = False
                p.queued = None
            if not p.connected:
                if now - p.seen >= REMOVE:
                    p.body = []
                    p.respawn = now + RESPAWN
                continue
            if not p.body:
                if now >= p.respawn:
                    self.spawn(p, now)
                continue
            direction = p.direction if p.queued is None else p.queued
            p.direction, p.queued = direction, None
            dx, dy = DIRECTIONS[direction]
            head = p.body[0][0]+dx, p.body[0][1]+dy
            own = p.body if head in self.food else p.body[:-1]
            if not (0 <= head[0] < COLUMNS and 0 <= head[1] < ROWS) or head in own:
                if now < p.protected:
                    stopped.add(p.id)
                else:
                    dead.add(p.id)
            proposals[p.id] = head
        # Conservative solid bodies also handle swaps and chains of blocked heads.
        # Staying in place is always legal; no arbitrary deflection into danger.
        for id, head in proposals.items():
            if any(head in other.body for other in self.players.values() if other.id != id):
                stopped.add(id)
            if sum(candidate == head for candidate in proposals.values()) > 1:
                stopped.add(id)
        for p in self.players.values():
            if p.id in dead:
                p.body, p.respawn = [], now + RESPAWN
            elif p.id in proposals and p.id not in stopped:
                head = proposals[p.id]
                p.body.insert(0, head)
                if head in self.food:
                    self.food.remove(head)
                    self.score += 1
                else:
                    p.body.pop()
        self.refill()

    def advance(self, now):
        if self.phase == "lobby" and now >= self.created + LOBBY:
            # Disconnected lobby members don't count toward the minimum.
            self.players = {id:p for id,p in self.players.items() if p.connected and now-p.seen < STALE}
            if len(self.players) < 2:
                self.phase, self.ended = "alone", self.created + LOBBY
            else:
                self.phase = "countdown"
                n = len(self.players)
                self.target, self.food_count = n*10, n*2+2
                for p in self.players.values():
                    self.spawn(p, self.start)
                self.refill()
            self.revision += 1
        if self.phase == "countdown" and now >= self.start:
            self.phase = "playing"
            self.revision += 1
        if self.phase == "playing":
            limit = min(now, self.start + DURATION - 1)
            while True:
                pending = [p.respawn for p in self.players.values()
                           if p.connected and not p.body and p.respawn]
                event = min([self.next_step, *pending])
                if event > limit:
                    break
                # Respawns occur at their own three-second deadline, rather than
                # being rounded up to the next 450ms movement step.
                for p in self.players.values():
                    if p.connected and not p.body and p.respawn and p.respawn <= event:
                        if event-p.seen < STALE:
                            self.spawn(p, event)
                        else:
                            p.connected = False
                if event == self.next_step:
                    self.move(event)
                    self.next_step += STEP
                self.revision += 1
            if now >= self.start + DURATION:
                self.phase, self.ended = "finished", self.start + DURATION
                self.revision += 1

    def snapshot(self, now):
        deadline = (self.created+LOBBY if self.phase == "lobby" else self.start
                    if self.phase == "countdown" else self.start+DURATION)
        return {"type":"state", "schemaVersion":1, "session":self.id,
                "revision":self.revision, "tick":self.tick, "phase":self.phase,
                "remainingMs":max(0, deadline-now) if not self.ended else 0,
                "score":self.score, "target":self.target, "columns":COLUMNS, "rows":ROWS,
                "stepMs":STEP, "fruitCount":self.food_count, "food":sorted(self.food),
                "players":[{"id":p.id, "avatar":p.avatar, "accentColor":p.accent,
                            "connected":p.connected, "body":list(p.body), "direction":p.direction,
                            "seq":p.seq, "respawnMs":max(0,p.respawn-now),
                            "protected":now < p.protected} for p in self.players.values()]}
