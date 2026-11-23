from contextlib import ExitStack
import itertools
import json
from pathlib import Path

import pytest

from app.models import Device, RangierwerkSettings
from app.services.devices import initialize_pages
from app.services.rangierwerk import CARD_MS, DRIVE_MS, RESERVATION_MS, SUMMARY_MS, YardService


class Clock:
    now = 0

    def __call__(self):
        return self.now


@pytest.fixture
def hub():
    clock = Clock()
    seeds = itertools.count(17)
    value = YardService(clock=clock, seed=lambda: next(seeds), generation=10)
    yield value
    value.yard.close()


def join(hub, index):
    return hub.join(f"leap-{index}", "#08d4a2", f"Lok {index}")


def command(hub, player, kind, **fields):
    packet = {"type": kind, "card": hub.generation, "seq": player.sequence + 1, **fields}
    return hub.message(player, player.token, packet)


def engine(hub, player):
    return next(v for v in hub.state()["vehicles"] if v[0] == player.slot)


def test_firmware_protocol_fixture(hub):
    expected = json.loads(Path(__file__).with_name("rangierwerk-v1.json").read_text())
    assert hub.snapshot(join(hub, 0)) == expected


def test_shared_orders_and_capacity_during_join_and_leave(hub):
    ids = [order[0] for order in hub.state()["orders"]]
    a = join(hub, 0)
    hub.clock.now += 2000
    b, c, d = [join(hub, index) for index in range(1, 4)]
    assert hub.remaining == CARD_MS - 2000
    assert len({engine(hub, p)[2] for p in (a, b, c, d)}) == 4
    assert join(hub, 4) is None
    orders = hub.state()["orders"]
    assert len(orders) == 4 and [order[0] for order in orders[:3]] == ids
    assert hub.snapshot(a)["orders"] == hub.snapshot(d)["orders"]
    assert not command(hub, c, "leave")
    assert hub.state()["orders"] == orders
    e = join(hub, 4)
    assert e.slot == c.slot and hub.state()["orders"] == orders


def test_expiring_drive_reconnect_and_reservation(hub):
    a = join(hub, 0)
    original = engine(hub, a)
    old_socket = a.token
    command(hub, a, "drive", direction=1)
    hub.clock.now = 40
    hub.advance()
    moved = engine(hub, a)
    assert moved[2] != original[2]
    hub.clock.now = DRIVE_MS + 1
    hub.advance()
    assert engine(hub, a) == moved and a.direction == 0
    hub.disconnect(a, old_socket)
    after_leave = hub.remaining
    hub.clock.now += 40000
    assert join(hub, 0) is a
    assert engine(hub, a) == moved and hub.remaining == after_leave
    assert not hub.message(a, old_socket, {"type": "leave"})
    hub.disconnect(a, a.token)
    hub.clock.now += RESERVATION_MS
    hub.advance()
    assert not hub.players
    assert not any(v[0] == a.slot for v in hub.state()["vehicles"])
    assert hub.remaining == after_leave


def test_game_time_counts_only_while_connected_and_applies_next_difficulty(hub):
    hub.clock.now = 90_000
    hub.advance()
    assert hub.remaining == CARD_MS
    a = join(hub, 0)
    hub.next_difficulty = 4
    assert hub.difficulty == 1
    for _ in range(600):
        hub.clock.now += 1000
        assert command(hub, a, "ping")
    assert hub.remaining == 0 and hub.summary == SUMMARY_MS and hub.seed == 17
    old_card = hub.generation
    hub.disconnect(a, a.token)
    hub.clock.now += 20_000
    b = join(hub, 1)
    assert hub.generation == old_card and hub.summary == SUMMARY_MS
    hub.clock.now += SUMMARY_MS
    hub.advance()
    assert hub.generation != old_card and hub.seed == 18 and hub.remaining == CARD_MS
    assert hub.difficulty == 4 and b.connected
    switches = hub.state()["switches"]
    command(hub, b, "turnout", card=old_card, index=0)
    assert hub.state()["switches"] == switches


def test_turnouts_are_serial_and_duplicate_commands_do_not_toggle_again(hub):
    a, b = join(hub, 0), join(hub, 1)
    packet = {"type": "turnout", "seq": 1, "card": hub.generation, "index": 0}
    hub.message(a, a.token, packet)
    assert hub.snapshot(b)["switches"] == 1
    hub.message(a, a.token, packet)
    assert hub.snapshot(b)["switches"] == 1
    hub.message(b, b.token, packet)
    assert hub.snapshot(a)["switches"] == 0


def make_device(db, index, enabled):
    d = Device(device_id=f"leap-{index}", name=f"Lok {index}", accent_color=f"#2244{index:02x}")
    initialize_pages(d)
    if enabled:
        d.enabled_games = ["rangierwerk"]
    db.add(d)
    db.commit()
    return d


def wait_state(ws, predicate):
    for _ in range(30):
        snapshot = ws.receive_json()
        if predicate(snapshot):
            return snapshot
    pytest.fail("No matching Rangierwerk snapshot")


def test_websocket_grants_reconnect_full_and_shared_state(client, db):
    for index in range(6):
        make_device(db, index, index != 5)

    def socket(index):
        return client.websocket_connect(f"/api/v1/devices/leap-{index}/rangierwerk/ws")

    with socket(5) as denied:
        assert denied.receive_json() == {"type": "error", "code": "game_disabled"}

    join_frame = {"type": "join", "protocolVersion": 1}
    with ExitStack() as connected:
        sockets = []
        for i in range(4):
            ws = connected.enter_context(socket(i))
            sockets.append(ws)
            ws.send_json({**join_frame, "accentColor": "#ffffff"})
            state = ws.receive_json()
            assert state["type"] == "state" and state["self"] == i
            assert [i, f"#2244{i:02x}", f"Lok {i}", True] in state["colors"]
        with socket(4) as full:
            full.send_json(join_frame)
            assert full.receive_json() == {"type": "full"}
        first, last = sockets[0], sockets[-1]
        state = wait_state(first, lambda s: len(s["orders"]) == 4)
        packet = {"type": "turnout", "seq": 1, "card": state["card"], "index": 0}
        last.send_json(packet)
        changed = wait_state(first, lambda s: s["switches"] == 1)
        assert changed["orders"] == state["orders"]
        with socket(3) as reopened:
            reopened.send_json(join_frame)
            new = reopened.receive_json()
            assert new["self"] == 3 and new["seed"] == state["seed"]
            assert new["vehicles"] == changed["vehicles"]
            reopened.send_json({"type": "leave"})
        wait_state(first, lambda s: len(s["colors"]) == 3)
        with socket(4) as free:
            free.send_json(join_frame)
            assert free.receive_json()["self"] == 3


def test_configured_difficulty_persists_and_does_not_replace_current_card(client, db):
    before = client.get("/api/v1/games/status").json()
    assert client.post("/games/rangierwerk", data={"difficulty": 5}).status_code == 422
    d = make_device(db, 7, False)
    config = f"/api/v1/devices/{d.device_id}/config"
    assert {"id": "rangierwerk", "enabled": False} in client.get(config).json()["games"]
    assert "Rangierwerk" in client.get(f"/devices/{d.id}").text
    form = {"name": d.name, "age": 9, "avatar": "dragon", "enabled": "on",
            "page_ids": ["games"], "game_settings": "true", "game_ids": ["rangierwerk"]}
    assert client.post(f"/devices/{d.id}", data=form).status_code == 200
    assert {"id": "rangierwerk", "enabled": True} in client.get(config).json()["games"]
    assert client.post("/games/rangierwerk", data={"difficulty": 3}, follow_redirects=False).status_code == 303
    assert db.get(RangierwerkSettings, 1).difficulty == 3

    def status(result):
        return next(g for g in result["games"] if g["id"] == "rangierwerk")["sessions"][0]

    after = status(client.get("/api/v1/games/status").json())
    assert after["session_id"] == status(before)["session_id"]
    assert {m["label"]: m["value"] for m in after["metrics"]}["Nächste Karte"] == "Güterbahnhof"
    assert after["remaining_ms"] == CARD_MS
    with db.get_bind().connect() as independent:
        assert independent.execute(RangierwerkSettings.__table__.select()).one().difficulty == 3
