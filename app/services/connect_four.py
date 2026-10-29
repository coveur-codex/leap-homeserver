"""Authoritative two-player matches. All calls run on the ASGI event loop."""
import math
import asyncio
import secrets
import time
from dataclasses import dataclass, field


@dataclass
class Player:
    id: str
    name: str
    accent: str
    connected: bool = True
    last_seen: float = 0
    disconnected_at: float | None = None
    seq: int = 0
    rematch: bool = False
    token: str = ""
    left: bool = False


@dataclass
class Match:
    session: str
    players: list[Player]
    deadline: float
    phase: str = "lobby"
    board: list = field(default_factory=lambda: [[0] * 7 for _ in range(6)])
    revision: int = 1
    turn: int = 0
    starter: int = 0
    move: int = 0
    winner: int = 0
    reason: str = ""
    saved_time: float = 30
    finished_at: float | None = None
    round: int = 0

    def finish(self, now, reason, winner=0):
        self.phase, self.reason, self.winner = "finished", reason, winner
        self.finished_at = now
        self.revision += 1

    def start(self, now, starter):
        self.board = [[0] * 7 for _ in range(6)]
        self.phase, self.reason, self.winner = "playing", "", 0
        self.starter = self.turn = starter
        self.move = 0
        self.round += 1
        self.deadline = now + 30
        self.finished_at = None
        for p in self.players:
            p.rematch = False
        self.revision += 1

    def advance(self, now):
        if self.phase == "finished":
            return
        # Heartbeats detect silent peers even if their TCP connection stays open.
        for p in self.players:
            if p.connected and now - p.last_seen >= 3:
                self.disconnect(p, p.last_seen + 3)
        if self.phase == "lobby":
            if now >= self.deadline:
                self.finish(now, "no_opponent")
        elif self.phase == "playing" and now >= self.deadline:
            self.finish(now, "turn_timeout", 3 - self.turn)
        elif self.phase == "paused":
            expired = [p for p in self.players if p.disconnected_at is not None and now >= p.disconnected_at + 30]
            if expired:
                winner = next((i + 1 for i, p in enumerate(self.players) if p.connected), 0)
                self.finish(now, "disconnect_timeout", winner)

    def disconnect(self, player, now):
        if not player.connected:
            return
        # A move deadline reached before a disconnect must still decide the game.
        if self.phase == "playing" and now >= self.deadline:
            self.finish(now, "turn_timeout", 3 - self.turn)
        player.connected = False
        player.disconnected_at = now
        if self.phase == "playing":
            self.saved_time = max(0, self.deadline - now)
            self.phase = "paused"
        self.revision += 1

    def remaining_ms(self, now):
        remaining = self.deadline - now
        if self.phase == "paused":
            remaining = min(p.disconnected_at + 30 - now for p in self.players if not p.connected)
        if self.phase == "finished":
            remaining = 0
        return max(0, math.ceil(remaining * 1000))

    def snapshot(self, now):
        return {"type": "state", "schemaVersion": 1, "session": self.session,
                "revision": self.revision, "phase": self.phase, "remainingMs": self.remaining_ms(now),
                "board": [row[:] for row in self.board], "turn": self.turn, "move": self.move,
                "round": self.round, "winner": self.winner, "reason": self.reason,
                "players": [{"id": p.id, "name": p.name, "accentColor": p.accent,
                             "connected": p.connected, "seq": p.seq, "rematch": p.rematch,
                             "left": p.left} for p in self.players]}


class Matchmaker:
    def __init__(self, clock=time.monotonic, choose=secrets.randbelow):
        self.clock, self.choose = clock, choose
        self.matches = {}
        self.members = {}
        self.task = None

    def start(self):
        self.matches.clear()
        self.members.clear()
        async def run():
            while True:
                self.advance()
                await asyncio.sleep(0.05)
        self.task = asyncio.create_task(run())

    async def stop(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
        self.matches.clear()
        self.members.clear()

    def status(self):
        from app.services.game_status import GameMetric, GameParticipant, GameSession
        labels = {"lobby": "Mitspieler werden gesucht", "playing": "Spiel läuft",
                  "paused": "Verbindungspause", "finished": "Partie beendet"}
        now = self.clock()
        return tuple(GameSession(
            session_id=m.session, phase=m.phase, label=labels[m.phase],
            activity="running" if m.phase in {"playing", "paused"} else "waiting" if m.phase=="lobby" else "finished",
            remaining_ms=m.remaining_ms(now), max_players=2,
            players=tuple(GameParticipant(p.id, p.connected) for p in m.players),
            metrics=(GameMetric("Runde", m.round), GameMetric("Züge", m.move)))
            for m in self.matches.values())

    def advance(self):
        now = self.clock()
        for key, match in list(self.matches.items()):
            match.advance(now)
            if match.finished_at is not None and now - match.finished_at >= 180:
                del self.matches[key]
                for p in match.players:
                    if self.members.get(p.id) == key:
                        del self.members[p.id]

    def join(self, device_id, name, accent, session=""):
        self.advance()
        now = self.clock()
        existing = self.matches.get(self.members.get(device_id))
        if session:
            match = self.matches.get(session)
            if not match or existing is not match:
                raise ValueError("session_lost")
            p = next(p for p in match.players if p.id == device_id)
            if p.left:
                raise ValueError("session_lost")
        elif existing and existing.phase != "finished":
            match = existing
            p = next(p for p in match.players if p.id == device_id)
        else:
            match = next((m for m in self.matches.values() if m.phase == "lobby" and
                          len(m.players) == 1 and m.players[0].connected), None)
            if match is None:
                if len(self.matches) >= 256:
                    raise ValueError("server_busy")
                match = Match(secrets.token_hex(16), [], now + 30)
                self.matches[match.session] = match
            p = Player(device_id, name, accent)
            match.players.append(p)
            self.members[device_id] = match.session
        p.connected, p.last_seen, p.disconnected_at = True, now, None
        p.token = secrets.token_hex(16)
        if match.phase == "lobby" and len(match.players) == 2:
            match.start(now, self.choose(2) + 1)
        elif match.phase == "paused" and all(p.connected for p in match.players):
            match.phase = "playing"
            match.deadline = now + match.saved_time
        match.revision += 1
        return match, p, p.token

    def message(self, match, player, token, frame):
        self.advance()
        if player.token != token or self.members.get(player.id) != match.session or player.left:
            raise ValueError("session_replaced")
        now = self.clock()
        if not isinstance(frame, dict):
            raise ValueError("invalid_message")
        kind = frame.get("type")
        if not isinstance(kind, str) or kind not in {"ping", "sync", "input", "rematch", "leave"}:
            raise ValueError("invalid_message")
        if not player.connected:
            raise ValueError("reconnect_required")
        player.last_seen = now
        if kind == "leave":
            player.left = True
            self.leave(match, player, token)
            return
        if kind in {"input", "rematch"}:
            seq = frame.get("seq")
            if type(seq) is not int or not 0 < seq <= 0xffffffff:
                raise ValueError("invalid_sequence")
            if seq <= player.seq:
                return
            player.seq = seq
            match.revision += 1
        if kind == "rematch":
            if (frame.get("round") == match.round and type(frame.get("round")) is int and
                    match.phase == "finished" and len(match.players) == 2 and all(
                    p.connected and not p.left and self.members.get(p.id) == match.session for p in match.players)):
                player.rematch = True
                if all(p.rematch for p in match.players):
                    match.start(now, 3 - match.starter)
        if kind != "input":
            return
        column = frame.get("column")
        if type(column) is not int or not 0 <= column < 7:
            raise ValueError("invalid_column")
        number = match.players.index(player) + 1
        if (match.phase != "playing" or match.turn != number or
                type(frame.get("round")) is not int or frame["round"] != match.round or
                type(frame.get("move")) is not int or frame["move"] != match.move or match.board[0][column]):
            return
        row = next(r for r in range(5, -1, -1) if match.board[r][column] == 0)
        match.board[row][column] = number
        match.move += 1
        for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
            length = 1
            for sign in (-1, 1):
                x, y = column + dx * sign, row + dy * sign
                while 0 <= x < 7 and 0 <= y < 6 and match.board[y][x] == number:
                    length += 1
                    x, y = x + dx * sign, y + dy * sign
            if length >= 4:
                match.finish(now, "four", number)
                return
        if match.move == 42:
            match.finish(now, "draw")
        else:
            match.turn = 3 - number
            match.deadline = now + 30

    def leave(self, match, player, token):
        if player.token != token:
            return
        now = self.clock()
        match.advance(now)
        match.disconnect(player, now)
        if player.left and match.phase != "finished":
            winner = next((i + 1 for i, p in enumerate(match.players) if p is not player and p.connected), 0)
            match.finish(now, "left", winner)


matchmaker = Matchmaker()
