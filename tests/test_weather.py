import pytest
from app.services import weather
from app.services.weather_icons import weather_icon, weather_kind, weather_label


@pytest.mark.asyncio
@pytest.mark.parametrize('unit', ['C', 'F'])
async def test_weather_current_and_local_tomorrow(monkeypatch, unit):
    captured = {}
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {'timezone': 'Pacific/Auckland',
                    'current': {'temperature_2m': 18, 'weather_code': 2, 'wind_speed_10m': 7, 'is_day': 0},
                    'daily': {'time': ['2026-10-05', '2026-10-06'], 'weather_code': [2, 95],
                              'temperature_2m_min': [9, 10], 'temperature_2m_max': [20, 22],
                              'precipitation_probability_max': [5, 70]}}
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url, params): captured.update(params); return Response()
    monkeypatch.setattr(weather.httpx, 'AsyncClient', Client)
    result = await weather.OpenMeteoProvider().current(50, 7, unit)
    assert captured['forecast_days'] == 2 and captured['timezone'] == 'auto'
    assert captured['temperature_unit'] == ('fahrenheit' if unit == 'F' else 'celsius')
    assert 'weather_code' in captured['daily'] and 'is_day' in captured['current']
    assert result['current']['isDay'] is False
    assert result['timezone'] == 'Pacific/Auckland'
    assert result['today']['min'] == 9
    assert result['tomorrow'] == {'date': '2026-10-06', 'weatherCode': 95, 'min': 10, 'max': 22, 'precipitationProbability': 70}


@pytest.mark.asyncio
async def test_missing_forecast_is_not_fabricated(monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {'current': {'temperature_2m': 0, 'weather_code': 45},
                    'daily': {'time': ['2026-10-04'], 'temperature_2m_min': [None], 'weather_code': [45]}}
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, *args, **kwargs): return Response()
    monkeypatch.setattr(weather.httpx, 'AsyncClient', Client)
    result = await weather.OpenMeteoProvider().current(50, 7, 'C')
    assert result['tomorrow'] is None
    assert result['today']['max'] is None
    assert result['current']['windSpeed'] is None
    assert result['current']['isDay'] is None


@pytest.mark.parametrize('code,kind', [(0,'clear'), (1,'mostly-clear'), (2,'partly-cloudy'), (3,'overcast'),
    (45,'fog'), (48,'fog'), (51,'drizzle'), (55,'drizzle'), (56,'freezing-rain'), (67,'freezing-rain'),
    (61,'rain'), (65,'rain'), (71,'snow'), (77,'snow'), (80,'showers'), (82,'showers'),
    (85,'snow-showers'), (86,'snow-showers'), (95,'thunder'), (96,'hail'), (99,'hail'), (None,'unknown'), (-1,'unknown')])
def test_weather_icons_cover_wmo_codes(code, kind):
    assert weather_kind(code) == kind
    svg = str(weather_icon(code))
    assert f'data-weather-icon="{kind}"' in svg and 'viewBox="0 0 64 64"' in svg
    assert '<text' not in svg and '<image' not in svg


def test_night_and_provider_text_are_safe():
    assert weather_label(0, False) == 'Klar'
    assert weather_icon(0, False) != weather_icon(0, True)
    assert '<script>' not in weather_icon('<script>')


def test_weather_preview_current_tomorrow_and_old_cache(client, db):
    from datetime import datetime, timezone
    from app.models import Device, LocationCache
    from app.services.devices import initialize_pages
    device = Device(device_id='weather-test', name='Weather', latitude=50, longitude=7)
    initialize_pages(device)
    next(page for page in device.pages if page.page_id == 'weather').enabled = True
    db.add(device); db.flush()
    cache = LocationCache(location_key='50.00000,7.00000', latitude=50, longitude=7,
        weather_fetched_at=datetime.now(timezone.utc), weather_data={
            'unit':'C', 'location':'Teststadt', 'current':{'temperature':0,'weatherCode':0,'isDay':False,'windSpeed':0},
            'today':{'min':-1,'max':5,'precipitationProbability':0},
            'tomorrow':{'date':'2026-10-05','weatherCode':95,'min':3,'max':12,'precipitationProbability':80}})
    db.add(cache); db.commit()
    page = client.get(f'/devices/{device.id}').text
    assert 'MORGEN' in page and 'Gewitter' in page and '3 bis 12° C' in page
    assert 'data-weather-icon="thunder"' in page and '>Klar<' in page
    assert '0 km/h' in page and 'Regen 0%' in page
    cache.weather_data = {**cache.weather_data, 'tomorrow': None}
    db.commit()
    assert 'Vorhersage fehlt' in client.get(f'/devices/{device.id}').text
