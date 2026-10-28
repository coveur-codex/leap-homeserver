from contextlib import ExitStack
import pytest
from starlette.websockets import WebSocketDisconnect
from app.api.snake import hub
from app.models import Device
from app.services.devices import initialize_pages


def devices(db,n=5):
    for i in range(n):
        d=Device(device_id=f'snake-{i}',name=f'Snake {i}',accent_color='#ff9933')
        initialize_pages(d); db.add(d)
    db.commit()


def join(client,id,stack,session=''):
    ws=stack.enter_context(client.websocket_connect(f'/api/v1/devices/{id}/snake/ws'))
    ws.send_json({'type':'join','session':session,'protocolVersion':2})
    return ws,ws.receive_json()


def test_socket_lobby_same_session_full_and_reconnect(client,db):
    devices(db)
    with ExitStack() as stack:
        sockets=[]
        for i in range(4):
            ws,state=join(client,f'snake-{i}',stack)
            sockets.append(ws)
            assert state['phase']=='lobby' and len(state['players'])==i+1
            assert state['session']==hub.room.id
            assert all(p['accentColor']=='#ff9933' for p in state['players'])
        fifth,error=join(client,'snake-4',stack)
        assert error['type']=='error'
        old_session=state['session']
    with ExitStack() as stack:
        ws,state=join(client,'snake-0',stack,old_session)
        assert state['session']==old_session and len(state['players'])==4
        assert state['players'][0]['connected']
        ws.send_json({'type':'sync'})
        assert ws.receive_json()['session']==old_session


def test_socket_restart_unknown_and_disabled(client,db):
    devices(db,1)
    with ExitStack() as stack:
        ws,error=join(client,'snake-0',stack,'f'*32)
        assert error['type']=='error' and hub.room is None
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/api/v1/devices/missing/snake/ws'): pass
    d=db.query(Device).first(); d.enabled_games=[]; db.commit()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/api/v1/devices/snake-0/snake/ws'): pass


def test_socket_rejects_malformed_and_oversized_frames(client,db):
    devices(db,1)
    with ExitStack() as stack:
        ws,state=join(client,'snake-0',stack)
        ws.send_json({'type':'input','seq':1,'tick':0,'direction':99})
        # A complete state can be queued before the validation error.
        result=ws.receive_json()
        while result['type']=='state': result=ws.receive_json()
        assert result['type']=='error'
    with client.websocket_connect('/api/v1/devices/snake-0/snake/ws') as ws:
        ws.send_text('x'*513)
        assert ws.receive_json()['type']=='error'


def test_authoritative_countdown_start_finish_and_no_late_join(client,db,monkeypatch):
    clock=[1000]
    monkeypatch.setattr('app.api.snake.now_ms',lambda:clock[0])
    devices(db,3)
    def phase(ws,name):
        for _ in range(20):
            state=ws.receive_json()
            if state.get('phase')==name: return state
        raise AssertionError('Expected phase '+name)
    with ExitStack() as stack:
        a,first=join(client,'snake-0',stack)
        assert first['remainingMs']==10000
        b,second=join(client,'snake-1',stack)
        assert second['session']==first['session']
        clock[0]=10999
        for ws in (a,b): ws.send_json({'type':'ping'})
        # Process both heartbeats before closing the lobby at its original deadline.
        phase(a,'lobby'); phase(b,'lobby')
        # Set server heartbeat timestamps to the same deterministic instant.
        for p in hub.room.players.values(): p.seen=10999
        clock[0]=11000; a.send_json({'type':'sync'})
        assert phase(a,'countdown')['remainingMs']==3000
        clock[0]=14000; a.send_json({'type':'ping'})
        assert phase(a,'playing')['remainingMs']==120000
        late,error=join(client,'snake-2',stack)
        assert error['type']=='error'
        clock[0]=134000; a.send_json({'type':'sync'})
        result=phase(a,'finished')
        assert result['remainingMs']==0 and result['target']==20


def test_old_firmware_cannot_join_new_grid(client,db):
    devices(db,1)
    with client.websocket_connect('/api/v1/devices/snake-0/snake/ws') as ws:
        ws.send_json({'type':'join','session':''})
        frame=ws.receive_json()
        assert frame['type']=='error' and 'Firmware' in frame['detail']
        assert hub.room is None
