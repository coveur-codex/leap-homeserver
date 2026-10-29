from app.api.snake import hub
from app.services.snake import Room
from app.services.game_status import GameMetric, GameParticipant, GameSession, GameStatusRegistry, registry


def test_generic_registry_supports_multiple_games_and_sessions():
    status = GameStatusRegistry()
    a = GameSession('a', 'round', 'Runde läuft', 'running', 30000,
                    (GameParticipant('leap-a', True),), 2, (GameMetric('Runde', 3),))
    b = GameSession('b', 'matching', 'Spielersuche', 'waiting', 9000)
    status.register('future_game', 'Weiteres Spiel', lambda: (a, b))
    status.register('other_game', 'Noch ein Spiel', lambda: ())
    snapshot = status.snapshot()
    assert snapshot['schemaVersion'] == 1
    assert snapshot['runningSessions'] == snapshot['waitingSessions'] == 1
    game = snapshot['games'][0]
    assert game['id'] == 'future_game' and len(game['sessions']) == 2
    assert game['sessions'][0]['metrics'][0] == {'label': 'Runde', 'value': 3}
    snapshot['games'][0]['sessions'][0]['players'][0]['device_id'] = 'changed'
    assert status.snapshot()['games'][0]['sessions'][0]['players'][0]['device_id'] == 'leap-a'


def test_failed_provider_does_not_hide_other_games():
    status = GameStatusRegistry()
    def broken(): raise RuntimeError('not for the UI')
    status.register('broken', 'Defekt', broken)
    status.register('healthy', 'Gesund', lambda: (GameSession('x', 'play', 'Aktiv', 'running', 1),))
    snapshot = status.snapshot()
    assert snapshot['games'][0]['error']
    assert not snapshot['games'][1]['error'] and snapshot['runningSessions'] == 1
    assert 'not for the UI' not in str(snapshot)


def test_status_page_idle_and_no_cache(client):
    response = client.get('/games')
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    assert 'Spielestatus' in response.text and 'Keine Partie aktiv' in response.text
    assert '/static/game-status.js' in response.text
    assert 'Einzelspiele auf den Geräten werden hier nicht erfasst' in response.text
    assert 'href="/games"' in client.get('/system').text
    snapshot = client.get('/api/v1/games/status')
    assert snapshot.headers['cache-control'] == 'no-store'
    assert snapshot.json()['runningSessions'] == snapshot.json()['waitingSessions'] == 0


def test_snake_status_tracks_lobby_play_reconnect_and_end(client, monkeypatch):
    clock = [1000]
    monkeypatch.setattr('app.api.snake.now_ms', lambda: clock[0])
    room = Room(clock[0]); hub.room = room
    room.join('leap-a', 'avatar-dragon', '#ff9900', clock[0])
    room.join('leap-b', 'avatar-frog', '#00ff00', clock[0])
    def snapshot():
        result = client.get('/api/v1/games/status').json()
        game = next(game for game in result['games'] if game['id'] == 'snake')
        return result, game['sessions'][0]
    result, session = snapshot()
    assert (result['runningSessions'], result['waitingSessions']) == (0, 1)
    assert session['phase'] == 'lobby' and session['remaining_ms'] == 10000
    assert len(session['players']) == 2 and session['max_players'] == 4
    for p in room.players.values(): p.seen = 10999
    clock[0] = 11000; room.advance(clock[0])
    assert snapshot()[1]['phase'] == 'countdown'
    clock[0] = 14000; room.advance(clock[0]); room.score = 17
    result, session = snapshot()
    assert result['runningSessions'] == 1 and result['waitingSessions'] == 0
    assert session['phase'] == 'playing' and session['remaining_ms'] == 120000
    assert {m['label']: m['value'] for m in session['metrics']} == {
        'Teampunkte': 17, 'Punkteziel': 20, 'Spielfeld': '53 × 16'}
    room.disconnect('leap-a', clock[0])
    assert not snapshot()[1]['players'][0]['connected']
    room.join('leap-a', '', '', clock[0])
    assert snapshot()[1]['players'][0]['connected']
    fragment = client.get('/games/status')
    assert 'Spiel läuft' in fragment.text and 'leap-a' in fragment.text and '17' in fragment.text
    assert fragment.headers['cache-control'] == 'no-store'
    assert '<!doctype' not in fragment.text  # The refresh replaces only the cards.
    clock[0] = 134000; room.advance(clock[0])
    result, session = snapshot()
    assert result['runningSessions'] == result['waitingSessions'] == 0
    assert session['phase'] == 'finished' and session['remaining_ms'] == 0
    assert 'Partie beendet' in client.get('/games/status').text
    hub.room = None
    assert 'Keine Partie aktiv' in client.get('/games/status').text


def test_new_games_render_without_template_changes_and_escape_text(client, monkeypatch):
    monkeypatch.setattr(registry, '_providers', dict(registry._providers))
    registry.register('future_game', '<script>name</script>', lambda: (
        GameSession('future', 'pause', 'Pausiert', 'waiting', 1000,
                    (GameParticipant('<b>device</b>', True),), 2,
                    (GameMetric('Level', '<img src=x onerror=bad()>'),)),))
    for path in ('/games', '/games/status'):
        page = client.get(path).text
        assert 'data-game-id="future_game"' in page and 'Pausiert' in page
        assert '&lt;script&gt;name&lt;/script&gt;' in page
        assert '<b>device</b>' not in page and '<img src=x' not in page
