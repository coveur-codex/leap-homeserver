import os
import sqlite3
import subprocess
import sys
import pytest
from sqlalchemy import select
from app.models import Device, RadioStation
from app.services.devices import initialize_pages


def device(db, name):
    d = Device(device_id=name, name=name)
    initialize_pages(d)
    next(p for p in d.pages if p.page_id == 'radio').enabled = True
    db.add(d)
    db.commit()
    return d


def config(client, d):
    response = client.get(f'/api/v1/devices/{d.device_id}/config')
    assert response.status_code == 200
    return response.json()


def save_device(client, d, stations, pages=('home', 'radio')):
    return client.post(f'/devices/{d.id}', data={
        'name': d.name, 'age': 8, 'avatar': 'dragon', 'enabled': 'true',
        'page_ids': list(pages), 'radio_station_ids': stations,
    }, follow_redirects=False)


def test_station_crud_grants_order_revocation_and_sync(client, db):
    first, second = device(db, 'first'), device(db, 'second')
    for name, position in [('Later', 20), ('First', 1), ('Off', 2)]:
        assert client.post('/radio', data={'name': name, 'url': f'https://radio.example/{name}.mp3',
            'position': position, 'enabled': name != 'Off'}, follow_redirects=False).status_code == 303
    rows = db.scalars(select(RadioStation).order_by(RadioStation.id)).all()
    ids = [s.id for s in rows]
    assert save_device(client, first, ids).status_code == 303
    assert save_device(client, second, [ids[0]]).status_code == 303
    assert [s['name'] for s in config(client, first)['radioStations']] == ['First', 'Later']
    assert [s['name'] for s in config(client, second)['radioStations']] == ['Later']
    previous = config(client, first)['configVersion']
    assert client.post(f'/radio/{ids[1]}', data={'name': 'Renamed', 'url': 'http://radio.example/live',
        'position': 30, 'enabled': True}, follow_redirects=False).status_code == 303
    assert config(client, first)['configVersion'] == previous + 1
    assert [s['name'] for s in config(client, first)['radioStations']] == ['Later', 'Renamed']
    assert client.get('/api/v1/devices/first/sync').json()['configVersion'] == previous + 1
    plan = client.post('/api/v1/devices/first/sync', json={
        'firmwareVersion': '1.6.0', 'installedAssets': {}, 'freeFlash': 7000000}).json()
    assert plan['configVersion'] == previous + 1
    assert client.get(plan['configUrl']).json()['radioStations'] == config(client, first)['radioStations']
    assert client.post(f'/radio/{ids[0]}', data={'name': 'Later', 'url': rows[0].url,
        'position': 20}, follow_redirects=False).status_code == 303
    assert config(client, second)['radioStations'] == []
    assert save_device(client, first, [ids[0]]).status_code == 303
    assert config(client, first)['radioStations'] == []
    assert save_device(client, first, [ids[1]], pages=('home',)).status_code == 303
    assert config(client, first)['radioStations'] == []
    assert not next(p for p in config(client, first)['pages'] if p['id'] == 'radio')['enabled']
    assert client.post(f'/radio/{ids[1]}/delete', follow_redirects=False).status_code == 303
    db.expire_all()
    assert ids[1] not in db.get(Device, first.id).radio_station_ids
    assert db.get(RadioStation, ids[1]) is None
    assert client.get('/radio').status_code == 200
    assert client.get(f'/devices/{first.id}').status_code == 200


@pytest.mark.parametrize('url', ['ftp://example.org/a.mp3', 'https://user:pass@example.org/a',
    'https://example.org/a.m3u8', 'https://example.org/a.aac', 'https://example.org:bad/a',
    'https://example.org/a\r\nHeader:bad', 'https://example.org/a#fragment'])
def test_invalid_stream_urls(client, url):
    assert client.post('/radio', data={'name': 'Radio', 'url': url}).status_code == 422


def test_invalid_grants_duplicates_and_names(client, db):
    d = device(db, 'test')
    assert save_device(client, d, [999]).status_code == 422
    assert client.post('/radio', data={'name': ' ', 'url': 'https://example.org/live'}).status_code == 422
    assert client.post('/radio', data={'name': 'A', 'url': 'https://example.org/live'}, follow_redirects=False).status_code == 303
    assert client.post('/radio', data={'name': 'B', 'url': 'https://example.org/live'}).status_code == 409
    for i in range(33): db.add(RadioStation(name=str(i), url=f'https://example.org/{i}'))
    db.commit()
    assert save_device(client, d, [s.id for s in db.scalars(select(RadioStation)).all()]).status_code == 422


def test_existing_device_migration(tmp_path):
    path = tmp_path / 'radio.db'
    env = {**os.environ, 'LEAP_DATABASE_URL': f'sqlite:///{path}', 'LEAP_DATA_DIR': str(tmp_path)}
    def migrate(target):
        subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', target], env=env, check=True, capture_output=True)
    migrate('0006')
    with sqlite3.connect(path) as connection:
        connection.execute("""INSERT INTO devices (id,device_id,name,child_name,age,avatar,avatar_name,
            communication_enabled,avatar_config,enabled,created_at,updated_at,config_version,news_version,
            weather_version,aircraft_version,quiz_version,knowledge_version,knowledge_source,home_slots,
            news_limit,news_max_age_hours,included_feed_ids,excluded_feed_ids,weather_location,temperature_unit,
            weather_fields,firmware_channel,content_selection,installed_assets)
            VALUES (1,'old','Old','',8,'dragon','',1,'{}',1,'2026-01-01','2026-01-01',7,1,1,1,1,1,
            'klexikon','{}',20,48,'[]','[]','','C','[]','stable','[]','{}')""")
        connection.execute("INSERT INTO device_pages (device_id,page_id,title,enabled,position,settings) VALUES (1,'news','News',1,3,'{}')")
    migrate('head')
    migrate('head')
    with sqlite3.connect(path) as connection:
        assert connection.execute('SELECT radio_station_ids,config_version FROM devices').fetchone() [0] == '[]'
        assert connection.execute("SELECT enabled FROM device_pages WHERE page_id='radio'").fetchone() == (0,)
        assert connection.execute("SELECT position FROM device_pages WHERE page_id='radio'").fetchone()[0] == connection.execute("SELECT MAX(position) FROM device_pages").fetchone()[0]
        assert connection.execute("SELECT enabled,position FROM device_pages WHERE page_id='news'").fetchone() == (1, 3)
