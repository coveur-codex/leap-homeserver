from datetime import datetime, timedelta, timezone
from app.models import Device, Article, Feed, Category, CommunicationMessage
from app.services.devices import initialize_pages


def test_notification_settings_altitude_and_duplicate(client, db):
    d = Device(device_id='notifications', name='Notifications')
    initialize_pages(d); db.add(d); db.commit()
    url = f'/devices/{d.id}'
    api = '/api/v1/devices/notifications/config'
    assert client.get(api).json()['notificationSounds'] == {'communication': True, 'news': True, 'aircraft': True}
    assert client.get(api).json()['locationAltitudeMeters'] == 0
    assert 'name="sound_aircraft"' in client.get(url).text
    form = {'name': d.name, 'age': 8, 'avatar': 'dragon', 'enabled': 'on',
            'notification_settings': 'true', 'sound_news': 'on', 'location_altitude_meters': '512'}
    assert client.post(url, data=form, follow_redirects=False).status_code == 303
    config = client.get(api).json()
    assert config['notificationSounds'] == {'communication': False, 'news': True, 'aircraft': False}
    assert config['locationAltitudeMeters'] == 512
    client.post(f'{url}/duplicate', follow_redirects=False)
    copied = client.get('/api/v1/devices/notifications-copy/config').json()
    assert copied['notificationSounds'] == config['notificationSounds']
    assert copied['locationAltitudeMeters'] == 512
    for invalid in ['nan', 'inf', '-501', '9001', 'abc']:
        assert client.post(url, data={**form, 'location_altitude_meters': invalid}, follow_redirects=False).status_code == 422
    assert client.post(url, data={**form, 'location_altitude_meters': ''}, follow_redirects=False).status_code == 303
    assert client.get(api).json()['locationAltitudeMeters'] == 0


def test_sender_color_is_an_immutable_relay_snapshot(client, db):
    d = Device(device_id='sender', name='Sender', accent_color='#ff9933')
    initialize_pages(d); db.add(d)
    m = CommunicationMessage(id='hello', text='Hallo', symbol='', active=True)
    db.add(m); db.commit()
    response = client.post('/api/v1/devices/sender/communication/messages', json={'eventId': 'color-1', 'templateId': 'hello'})
    assert response.status_code == 200
    assert response.json()['message']['accentColor'] == '#ff9933'
    d.accent_color = '#112233'; db.commit()
    response = client.post('/api/v1/devices/sender/communication/messages', json={'eventId': 'color-1', 'templateId': 'hello'})
    assert response.json()['message']['accentColor'] == '#ff9933'


def test_news_has_arrival_timestamp(client, db):
    category = Category(slug='test-notifications', name='Test')
    feed = Feed(name='Test', url='https://example.com/feed', category=category)
    d = Device(device_id='news-notify', name='News', categories=[category])
    initialize_pages(d); db.add_all([feed, d]); db.flush()
    fetched = datetime.now(timezone.utc)
    article = Article(feed_id=feed.id, category=category.slug, title='Title', summary='Text',
                      source='Test', url='https://example.com/article', published_at=fetched-timedelta(hours=1),
                      fetched_at=fetched, hash='notification-test')
    db.add(article); db.commit()
    rows = client.get('/api/v1/devices/news-notify/news').json()['articles']
    assert rows[0]['fetchedEpoch'] == int(fetched.timestamp())


def test_observer_altitude_is_not_shared_between_devices(client, db, monkeypatch):
    from app.api import routes
    data = {'aircraft': [], 'center': {'latitude': 50, 'longitude': 7}, 'ageSeconds': 0}
    async def cached(*args): return data
    monkeypatch.setattr(routes, 'data_for_device', cached)
    for did, altitude in [('valley', None), ('hill', 350)]:
        d = Device(device_id=did, name=did, latitude=50, longitude=7, location_altitude_meters=altitude)
        initialize_pages(d); db.add(d)
    db.commit()
    assert client.get('/api/v1/devices/valley/aircraft').json()['center']['altitudeMeters'] == 0
    assert client.get('/api/v1/devices/hill/aircraft').json()['center']['altitudeMeters'] == 350
    assert 'altitudeMeters' not in data['center']
