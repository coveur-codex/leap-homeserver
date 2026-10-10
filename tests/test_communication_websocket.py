from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect
import pytest
from app.models import Device
from test_communication_relay import devices, send

@pytest.fixture
def db(tmp_path, monkeypatch):
    # Concurrent HTTP/socket sessions need independent connections, just as in
    # production. A shared StaticPool connection lets one rollback another.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.core.database import Base
    from app.core.config import settings
    monkeypatch.setattr(settings, 'data_dir', tmp_path)
    engine = create_engine(f"sqlite:///{tmp_path / 'relay.db'}", connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        yield session
    engine.dispose()

BASE = '/api/v1/devices'

def sync(ws, since=None):
    ws.send_json({'type':'sync', **({} if since is None else {'since': since})})
    return ws.receive_json()

def test_push_http_and_socket_sends_retry_and_reconnect(client, db):
    template = devices(db)
    with client.websocket_connect(f'{BASE}/b/communication/ws') as b:
        seed = sync(b)
        assert seed['type'] == 'messages' and seed['cursor'] == 0
        b.send_json({'type':'sync', 'since':0})
        send(client, template)
        page = b.receive_json()
        assert page['messages'][0]['senderId'] == 'a'
        cursor = page['cursor']
        b.send_json({'type':'sync', 'since':cursor})
        with client.websocket_connect(f'{BASE}/a/communication/ws') as a:
            assert sync(a)['cursor'] == cursor
            a.send_json({'type':'sync', 'since':cursor})
            request = {'type':'send', 'eventId':'socket-id', 'templateId':template}
            a.send_json(request)
            ack = a.receive_json()
            assert ack['type'] == 'ack' and ack['ok']
            own = a.receive_json()
            assert own['cursor'] == cursor+1
            pushed = b.receive_json()
            assert pushed['messages'] == own['messages']
            a.send_json({'type':'sync', 'since':own['cursor']})
            a.send_json(request)
            assert a.receive_json() == ack
            a.send_json({'type':'ping'})
            assert a.receive_json() == {'type':'pong'}
    send(client, template, event='while-offline')
    with client.websocket_connect(f'{BASE}/b/communication/ws') as b:
        caught = sync(b, cursor)
        assert len(caught['messages']) == 2
        assert caught['cursor'] == cursor+2


def test_backpressure_pages_and_restore(client, db):
    template = devices(db)
    with client.websocket_connect(f'{BASE}/b/communication/ws') as b:
        assert sync(b)['cursor'] == 0
        for i in range(20):
            send(client, template, event=f'event-{i}')
        b.send_json({'type':'ping'})
        assert b.receive_json() == {'type':'pong'}
        page = sync(b, 0)
        assert len(page['messages']) == 8 and page['more']
        page = sync(b, page['cursor'])
        assert len(page['messages']) == 8 and page['more']
        page = sync(b, page['cursor'])
        assert len(page['messages']) == 4 and not page['more']
    with client.websocket_connect(f'{BASE}/b/communication/ws') as b:
        reset = sync(b, 999)
        assert reset['reset'] and len(reset['messages']) == 8


def test_permissions_invalid_frames_and_templates(client, db):
    devices(db)
    with client.websocket_connect(f'{BASE}/b/communication/ws') as b:
        sync(b)
        b.send_json({'type':'send','eventId':'bad','templateId':'missing'})
        assert b.receive_json()['status'] == 422
        b.send_json({'type':'sync','since':True})
        with pytest.raises(WebSocketDisconnect) as error:
            b.receive_json()
        assert error.value.code == 1008
    with client.websocket_connect(f'{BASE}/b/communication/ws') as b:
        sync(b)
        device = db.scalar(select(Device).where(Device.device_id == 'b'))
        device.communication_enabled = False
        db.commit()
        b.send_json({'type':'ping'})
        with pytest.raises(WebSocketDisconnect) as error:
            b.receive_json()
        assert error.value.code == 1008
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f'{BASE}/b/communication/ws'):
            pass


@pytest.mark.parametrize('binary', [False, True])
def test_malformed_socket_frame_closes_cleanly(client, db, binary):
    devices(db)
    with client.websocket_connect(f'{BASE}/b/communication/ws') as socket:
        sync(socket)
        if binary:
            socket.send_bytes(b'not-json')
        else:
            socket.send_text('not-json')
        with pytest.raises(WebSocketDisconnect) as error:
            socket.receive_json()
        assert error.value.code == 1008
