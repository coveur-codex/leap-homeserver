from collections import deque

from app.core.games import DEFAULT_GAMES
from app.models import Device
from app.services.devices import initialize_pages
from app.services.pfuetzenpost import PondService, SETTLE_SECONDS, TURN_SECONDS


def send(hub, membership, kind, seq=1, turn=None):
    room, _, _ = membership
    return hub.message(*membership, {"type": kind, "seq": seq, "turnId": room.turn_id if turn is None else turn})


def test_dice_are_hidden_until_stop_pasches_clamp_and_final_round_finishes():
    now = [0.0]
    choices = deque((0, 0, 0, 0, 1))
    hub = PondService(clock=lambda: now[0], choose=lambda _: choices.popleft())
    a = hub.join("a", "Ada", "#112233", "")
    b = hub.join("b", "Bert", "#11ff33", "")
    room = a[0]
    send(hub, b, "start")
    assert room.phase == "lobby"
    send(hub, a, "start")
    assert room.active == 0 and room.round == 1
    room.positions[:2] = [10, 11]
    send(hub, b, "roll", 2)
    assert room.pending is None
    send(hub, a, "roll", 2)
    assert room.pending == (0, 0)
    rolling = room.snapshot(1, now[0])
    assert rolling["dice"] == (255, 255) and rolling["positions"] == [10, 11, 0, 0]
    assert "pending" not in rolling
    send(hub, a, "stop", 3)
    send(hub, a, "stop", 3)
    assert room.phase == "settling" and room.move == 1
    assert room.positions == [12, 11, 0, 0] and room.winners == 1
    assert rolling["positions"] == [10, 11, 0, 0]
    now[0] += SETTLE_SECONDS
    hub.advance()
    assert room.phase == "ready" and room.active == 1
    send(hub, b, "roll", 2, room.turn_id - 1)
    assert room.phase == "ready"
    now[0] += TURN_SECONDS + 0.01  # Idle turn rolls the same two dice.
    hub.advance()
    assert room.positions == [12, 12, 0, 0] and room.winners == 3
    now[0] += SETTLE_SECONDS + 0.01
    hub.advance()
    assert room.phase == "finished" and room.reason == "delivered"


def test_reconnect_guards_socket_and_keeps_pending_dice_then_retires_absent_player():
    now = [0.0]
    hub = PondService(clock=lambda: now[0], choose=lambda _: 0)
    a = hub.join("a", "Ada", "#ffffff", "")
    b = hub.join("b", "Ben", "#000000", "")
    c = hub.join("c", "Cem", "#112233", "")
    room = a[0]
    send(hub, a, "start")
    send(hub, a, "roll", 2)
    now[0] = 5
    hub.disconnect(*a)
    assert room.snapshot(1, now[0])["phase"] == "paused"
    assert room.remaining_ms(now[0]) == 30000
    now[0] = 24
    resumed = hub.join("a", "Ada", "#ffffff", room.id)
    hub.disconnect(*a)  # The old socket cannot remove the new one.
    assert room.snapshot(0, now[0])["ack"] == 2
    assert room.remaining_ms(now[0]) == 15000
    assert room.phase == "rolling" and room.pending == (0, 0)
    assert not send(hub, a, "stop", 3)
    send(hub, resumed, "stop", 3)
    now[0] += SETTLE_SECONDS + 0.01
    hub.advance()
    assert room.active == 1
    hub.disconnect(*b)
    now[0] += 30
    hub.advance()
    assert room.phase == "ready" and room.active == 2 and len(room.seats) == 2
    assert room.frog(1) == {"name": "Ben", "color": "#000000", "human": False, "connected": False}
    send(hub, c, "leave")
    assert room.phase == "finished" and room.reason == "players_left"


def test_four_seats_second_room_and_timeout_during_roll():
    now = [0.0]
    choices = deque((3, 0, 2))
    hub = PondService(clock=lambda: now[0], choose=lambda _: choices.popleft())
    players = [hub.join(str(i), f"Frosch {i}", "#00d7c5", "") for i in range(5)]
    room = players[0][0]
    assert all(member[0] is room for member in players[:4])
    assert players[4][0] is not room
    send(hub, players[0], "start")
    assert room.active == 3
    send(hub, players[3], "roll")
    now[0] = TURN_SECONDS
    hub.advance()
    assert not choices and room.dice == (0, 2) and room.positions == [1, 0, 1, 0]
    now[0] += SETTLE_SECONDS + 0.01
    hub.advance()
    assert room.active == 0 and players[4][0].phase == "lobby"


def test_host_transfer_during_lobby_survives_seat_reuse():
    hub = PondService(choose=lambda _: 0)
    first = hub.join("a", "Ada", "#ffffff", "")
    second = hub.join("b", "Ben", "#000000", "")
    send(hub, first, "leave")
    replacement = hub.join("c", "Cem", "#112233", "")
    room = replacement[0]
    assert replacement[1] == 0 and room.host == second[1] == 1
    send(hub, replacement, "start")
    assert room.phase == "lobby"
    send(hub, second, "start")
    assert room.phase == "ready"


def test_device_grant_lobby_and_accent_color_through_real_websockets(client, db):
    for i, color in enumerate(('#0022e0', '#0022e0', '#ee9900')):
        device = Device(device_id=f"frog-{i}", name=f"Gerät {i}", child_name=f"Kind {i}", accent_color=color)
        initialize_pages(device)
        device.enabled_games = [*DEFAULT_GAMES, "pfuetzenpost"] if i < 2 else DEFAULT_GAMES
        db.add(device)
    db.commit()
    endpoint = "/api/v1/devices/frog-{}/pfuetzenpost/ws"
    game_config = client.get("/api/v1/devices/frog-0/config").json()["games"]
    assert {"id": "pfuetzenpost", "enabled": True} in game_config
    join = {"type": "join", "protocolVersion": 1, "session": ""}
    with client.websocket_connect(endpoint.format(2)) as disabled:
        assert disabled.receive_json() == {"type": "error", "code": "game_disabled"}
    with client.websocket_connect(endpoint.format(0)) as host:
        host.send_json(join)
        solo = host.receive_json()
        assert solo["phase"] == "lobby" and solo["self"] == 0
        with client.websocket_connect(endpoint.format(1)) as guest:
            guest.send_json(join)
            lobby = guest.receive_json()
            assert lobby["session"] == solo["session"] and lobby["self"] == 1
            assert lobby["frogs"][0]["color"] == lobby["frogs"][1]["color"] == "#0022e0"
            assert host.receive_json()["frogs"][1]["name"] == "Kind 1"
            host.send_json({"type": "start", "seq": 1, "turnId": 0})
            first = host.receive_json()
            assert guest.receive_json()["phase"] == "ready"
            actor = host if first["turn"] == 0 else guest
            actor.send_json({"type": "roll", "seq": 2, "turnId": first["turnId"]})
            assert host.receive_json()["dice"] == [255, 255]
            assert guest.receive_json()["phase"] == "rolling"
            actor.send_json({"type": "stop", "seq": 3, "turnId": first["turnId"]})
            result = guest.receive_json()
            assert result["phase"] == "settling" and sum(result["positions"]) == 2
            assert [result["positions"][i] for i in result["dice"]] == (
                [2, 2] if result["dice"][0] == result["dice"][1] else [1, 1])
            status = client.get("/api/v1/games/status").json()
            assert any(g["id"] == "pfuetzenpost" and g["sessions"] for g in status["games"])
