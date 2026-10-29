import pytest
from app.services.connect_four import Matchmaker
from app.models import Device
from app.services.devices import initialize_pages

@pytest.fixture
def arena():
    now = [0.0]
    return Matchmaker(clock=lambda: now[0], choose=lambda _: 0), now

def pair(games, first="a", second="b"):
    m, p, t = games.join(first, "Änne", "#123456")
    same, q, u = games.join(second, "Ben", "#123456")
    assert same is m
    return m, (p, t), (q, u)

def send(games, match, actor, kind="input", **fields):
    p, token = actor
    games.message(match, p, token, {"type": kind, "seq": p.seq + 1,
                                  "round": match.round, "move": match.move, **fields})

def keepalive(match, now):
    for p in match.players:
        if p.connected: p.last_seen = now

def test_parallel_pairing_and_duplicate_devices(arena):
    games, _ = arena
    m, a, b = pair(games)
    n, c, d = pair(games, "c", "d")
    assert m is not n and len(m.players) == len(n.players) == 2
    again, p, token = games.join("a", "forged", "#ffffff")
    assert again is m and len(m.players) == 2 and p.accent == "#123456"
    games.leave(m, *a)
    assert p.connected
    with pytest.raises(ValueError, match="session_replaced"): send(games, m, a, column=0)
    send(games, m, (p, token), column=0)
    assert m.move == 1 and n.move == 0 and all(not any(row) for row in n.board)

@pytest.mark.parametrize("columns", [[0,6,1,6,2,5,3], [0,1,0,1,0,1,0],
                                    [0,1,1,2,3,2,2,3,4,3,3], [6,5,5,4,3,4,4,3,2,3,3]])
def test_winning_directions(arena, columns):
    games, _ = arena
    match, a, b = pair(games)
    for col in columns: send(games, match, a if match.turn == 1 else b, column=col)
    assert match.phase == "finished" and match.winner == 1 and match.reason == "four"
    previous = match.snapshot(0)
    send(games, match, b, column=6)
    assert match.board == previous["board"]

def test_invalid_stale_duplicate_full_columns(arena):
    games, _ = arena
    match, a, b = pair(games)
    send(games, match, b, column=0)
    assert match.move == 0
    for col in (-1, 7, True, "0", None):
        with pytest.raises(ValueError): send(games, match, a, column=col)
    for _ in range(6): send(games, match, a if match.turn == 1 else b, column=0)
    send(games, match, a, column=0)
    send(games, match, a, column=1, move=5)
    send(games, match, a, column=1, round=0)
    assert match.move == 6
    send(games, match, a, column=1)
    games.message(match, a[0], a[1], {"type":"input", "seq":a[0].seq, "column":2, "round":1, "move":7})
    assert match.move == 7 and match.deadline == 30

def test_draw(arena):
    games, _ = arena
    match, a, b = pair(games)
    match.board = [[1 if ((c//2+r)%2) else 2 for c in range(7)] for r in range(6)]
    match.board[0][0] = 0
    match.turn, match.move = 2, 41
    send(games, match, b, column=0)
    assert match.phase == "finished" and match.winner == 0 and match.reason == "draw"

def test_lobby_deadline_and_late_join(arena):
    games, now = arena
    match, _, _ = games.join("a", "A", "#ffffff")
    now[0] = 29.999
    keepalive(match, now[0]); games.advance()
    assert match.phase == "lobby"
    now[0] = 30
    later, _, _ = games.join("b", "B", "#ffffff")
    assert match.phase == "finished" and match.reason == "no_opponent" and later is not match

def test_exact_turn_deadline(arena):
    games, now = arena
    match, a, b = pair(games)
    now[0] = 29.999
    keepalive(match, now[0]); games.advance()
    assert match.phase == "playing"
    now[0] = 30
    send(games, match, a, column=0)
    assert match.phase == "finished" and match.winner == 2 and match.move == 0

def test_pause_resume_keeps_remaining_turn_time(arena):
    games, now = arena
    match, a, b = pair(games)
    now[0] = 8
    keepalive(match, now[0]); games.leave(match, *a)
    assert match.phase == "paused" and match.saved_time == 22
    now[0] = 32
    keepalive(match, now[0])
    resumed, p, token = games.join("a", "A", "#ffffff", match.session)
    assert resumed is match and match.phase == "playing" and match.deadline == 54 and match.turn == 1
    games.leave(match, *a)
    assert p.connected
    send(games, match, (p, token), column=4)
    assert match.board[5][4] == 1

def test_disconnect_timeout_and_both_disconnected(arena):
    games, now = arena
    match, a, b = pair(games)
    games.leave(match, *a)
    now[0] = 30
    keepalive(match, now[0]); games.advance()
    assert match.phase == "finished" and match.winner == 2 and match.reason == "disconnect_timeout"
    other, c, d = pair(games, "c", "d")
    games.leave(other, *c); games.leave(other, *d)
    now[0] = 60
    games.advance()
    assert other.phase == "finished" and other.winner == 0

def test_silent_peer_pauses_after_three_seconds(arena):
    games, now = arena
    match, a, b = pair(games)
    now[0] = 3; b[0].last_seen = 3
    games.advance()
    assert match.phase == "paused" and match.saved_time == 27 and not a[0].connected
    now[0] = 33; b[0].last_seen = 33
    games.advance()
    assert match.winner == 2

def test_rematch_requires_both_and_alternates(arena):
    games, _ = arena
    match, a, b = pair(games)
    match.finish(0, "four", 1)
    send(games, match, a, "rematch")
    send(games, match, b, "rematch", round=0)
    assert match.phase == "finished" and a[0].rematch
    send(games, match, b, "rematch")
    assert match.phase == "playing" and match.turn == 2 and match.round == 2
    assert match.move == 0 and not a[0].rematch and not b[0].rematch
    match.finish(0, "four", 2)
    send(games, match, a, "rematch"); send(games, match, b, "rematch")
    assert match.turn == 1 and match.round == 3

def test_leave_and_retention(arena):
    games, now = arena
    match, a, b = pair(games)
    send(games, match, a, "leave")
    assert match.phase == "finished" and match.reason == "left" and match.winner == 2
    send(games, match, b, "rematch")
    assert match.phase == "finished"
    with pytest.raises(ValueError, match="session_lost"): games.join("a", "A", "#ffffff", match.session)
    now[0] = 180; games.advance()
    assert not games.matches and not games.members

def test_new_search_invalidates_old_membership(arena):
    games, _ = arena
    match, a, b = pair(games)
    match.finish(0, "four", 1)
    newer, _, _ = games.join("a", "A", "#ffffff")
    assert newer is not match
    send(games, match, b, "rematch")
    assert match.phase == "finished"
    with pytest.raises(ValueError, match="session_lost"): games.join("a", "A", "#ffffff", match.session)

def test_random_start_and_foreign_session(arena):
    games, _ = arena
    games.choose = lambda _: 1
    match, a, b = pair(games)
    assert match.turn == 2
    with pytest.raises(ValueError, match="session_lost"): games.join("c", "C", "#ffffff", match.session)

def add_device(db, did, color="#123456"):
    d = Device(device_id=did, name=did, accent_color=color)
    initialize_pages(d); db.add(d); db.commit()
    return d

@pytest.fixture
def ws_games(monkeypatch, arena):
    monkeypatch.setattr("app.api.connect_four.matchmaker", arena[0])
    return arena

def receive_until(ws, predicate):
    for _ in range(20):
        frame = ws.receive_json()
        if predicate(frame): return frame
    pytest.fail("Expected WebSocket state not received")

def join_ws(ws, session=""):
    ws.send_json({"type":"join", "protocolVersion":1, "session":session, "accentColor":"#ffffff", "id":"forged"})
    return ws.receive_json()

def test_websocket_parallel_rooms_identity_reconnect(ws_games, client, db):
    for did in ("a","b","c","d"): add_device(db, did)
    url = "/api/v1/devices/{}/connect-four/ws"
    with client.websocket_connect(url.format("a")) as a, client.websocket_connect(url.format("b")) as b:
        first = join_ws(a)
        assert first["phase"] == "lobby" and first["players"][0]["accentColor"] == "#123456"
        second = join_ws(b)
        assert second["phase"] == "playing" and second["session"] == first["session"]
        with client.websocket_connect(url.format("c")) as c, client.websocket_connect(url.format("d")) as d:
            third, fourth = join_ws(c), join_ws(d)
            assert fourth["session"] == third["session"] != first["session"]
            status = client.get("/api/v1/games/status").json()
            game = next(g for g in status["games"] if g["id"] == "connect_four")
            assert len(game["sessions"]) == 2 and status["runningSessions"] == 2
            assert all(s["max_players"] == 2 and len(s["players"]) == 2 for s in game["sessions"])
            assert "Vier Gewinnt" in client.get("/games").text

            a.send_json({"type":"input", "seq":1, "round":1, "move":0, "column":3})
            frame = receive_until(b, lambda f:f.get("move") == 1)
            assert frame["board"][5][3] == 1 and third["move"] == fourth["move"] == 0
        a.close()
        paused = receive_until(b, lambda f:f.get("phase") == "paused")
        with client.websocket_connect(url.format("a")) as again:
            resumed = join_ws(again, paused["session"])
            assert resumed["phase"] == "playing" and resumed["move"] == 1
            assert resumed["players"][0]["seq"] == 1

@pytest.mark.parametrize("problem", ["unknown","disabled","page_disabled","game_disabled","protocol","session"])
def test_websocket_rejection_leaves_no_slot(ws_games, client, db, problem):
    d = add_device(db, "a")
    if problem == "disabled": d.enabled = False
    if problem == "page_disabled": next(p for p in d.pages if p.page_id == "games").enabled = False
    if problem == "game_disabled": d.enabled_games = ["snake"]
    db.commit()
    with client.websocket_connect(f"/api/v1/devices/{'unknown' if problem == 'unknown' else 'a'}/connect-four/ws") as ws:
        ws.send_json({"type":"join", "protocolVersion":2 if problem == "protocol" else 1,
                      "session":"a"*32 if problem == "session" else ""})
        assert ws.receive_json()["type"] == "error"
    assert not ws_games[0].matches

def test_accent_config_and_web_form(client, db):
    d = add_device(db, "a", "#ab12ef")
    config = client.get("/api/v1/devices/a/config").json()
    assert config["accentColor"] == "#ab12ef" and {"id":"connect_four","enabled":True} in config["games"]
    response = client.post(f"/devices/{d.id}", data={"name":"A", "age":8, "avatar":"dragon",
                                                   "accent_color":"#987654", "enabled":"true", "page_ids":["games"]})
    assert response.status_code == 200
    assert client.get("/api/v1/devices/a/config").json()["accentColor"] == "#987654"
    assert client.post(f"/devices/{d.id}", data={"name":"A","age":8,"avatar":"dragon","accent_color":"red"}).status_code == 422


@pytest.mark.asyncio
async def test_background_deadlines_and_lifecycle_without_sockets(arena):
    import asyncio
    games, now = arena
    games.start()
    match, _, _ = games.join("a", "A", "#123456")
    now[0] = 30
    await asyncio.sleep(0.06)
    assert match.phase == "finished" and match.reason == "no_opponent"
    now[0] = 210
    await asyncio.sleep(0.06)
    assert not games.matches
    await games.stop()
    assert games.task is None and not games.members


def test_status_is_read_only_and_counts_paused_match(arena):
    games, now = arena
    match, a, b = pair(games)
    games.leave(match, *a)
    now[0] = 100
    revision = match.revision
    status = games.status()
    assert status[0].phase == "paused" and status[0].activity == "running"
    assert status[0].remaining_ms == 0 and match.revision == revision
