"""Read-only runtime status contract for server-managed games.

Providers and readers run on the ASGI event loop, alongside the simulations.
A new game registers a provider; templates and API do not need game-specific code.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable, Literal
import logging
import re


@dataclass(frozen=True)
class GameParticipant:
    device_id: str
    connected: bool


@dataclass(frozen=True)
class GameMetric:
    label: str
    value: int | str


@dataclass(frozen=True)
class GameSession:
    session_id: str
    phase: str
    label: str
    activity: Literal["waiting", "running", "finished"]
    remaining_ms: int
    players: tuple[GameParticipant, ...] = ()
    max_players: int = 0
    metrics: tuple[GameMetric, ...] = ()


class GameStatusRegistry:
    def __init__(self):
        self._providers: dict[str, tuple[str, Callable[[], tuple[GameSession, ...]]]] = {}

    def register(self, game_id: str, name: str, provider: Callable[[], tuple[GameSession, ...]]):
        if not re.fullmatch(r"[a-z][a-z0-9_\-]{0,63}", game_id):
            raise ValueError("Invalid game ID")
        # Repeated application startup may register the same long-lived service.
        self._providers[game_id] = (name, provider)

    def snapshot(self):
        games, running, waiting = [], 0, 0
        for game_id, (name, provider) in sorted(self._providers.items()):
            try:
                sessions = [asdict(session) for session in provider()]
                error = False
            except Exception:
                logging.getLogger("leap").exception("game_status_failed game=%s", game_id)
                sessions, error = [], True
            running += sum(s["activity"] == "running" for s in sessions)
            waiting += sum(s["activity"] == "waiting" for s in sessions)
            games.append({"id": game_id, "name": name, "sessions": sessions, "error": error})
        return {"schemaVersion": 1, "generatedAt": datetime.now(timezone.utc).isoformat(),
                "runningSessions": running, "waitingSessions": waiting, "games": games}


registry = GameStatusRegistry()
