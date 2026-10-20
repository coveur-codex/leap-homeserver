from datetime import timedelta
import pytest
from sqlalchemy import select
from app.models import Device, FinanceCache
from app.services.devices import initialize_pages
from app.services import finance as f


def device(db, name="finance-one", symbols=None, enabled=True):
    d = Device(device_id=name, name=name)
    initialize_pages(d)
    page = next(p for p in d.pages if p.page_id == "finance")
    page.enabled = enabled
    page.settings = {"symbols": symbols or []}
    db.add(d); db.commit()
    return d


def quote(symbol="AAPL", market="open"):
    now = int(f.utcnow().timestamp())
    return {"symbol": symbol, "name": "Apple Inc.", "currency": "USD", "timestamp": now,
            "price": 110.0, "open": 100.0, "high": 112.0, "low": 99.0,
            "changePercent": 10.0, "session": "2026-10-20", "timezone": "America/New_York",
            "market": market, "points": [[now-300, 109.0], [now, 110.0]],
            "chartMode": "collected", "samples": [[now, 110.0]], "meta": {"private": "metadata"}}


class FakeProvider:
    name = "finnhub"
    def __init__(self): self.calls = []; self.error = None; self.headlines = 0
    async def quote(self, db, symbol, previous):
        self.calls.append(symbol)
        if self.error: raise self.error
        return quote(symbol)
    async def news(self, db, symbol, q):
        self.headlines += 1
        return {"title": "Company earnings", "source": "News", "timestamp": q["timestamp"]}


@pytest.fixture
def provider(monkeypatch):
    api = FakeProvider()
    monkeypatch.setitem(f.PROVIDERS, "finnhub", api)
    monkeypatch.setattr(f.settings, "finance_provider", "finnhub")
    return api


def test_symbols_and_actual_time_downsampling():
    assert f.normalize_symbol(" aapl ") == "AAPL"
    assert f.normalize_symbol("^GDAXI") == "^GDAXI"
    for value in ["", "../a", "a b", "<script>", "a"*33]:
        with pytest.raises(ValueError): f.normalize_symbol(value)
    points = [[i*300, float(i+1)] for i in range(1, 301)]
    points[120][1] = 1000.0
    result = f.reduce_points(points)
    assert len(result) <= 60 and result[0] == points[0] and result[-1] == points[-1]
    assert points[120] in result
    assert all(p in points for p in result)
    assert f.reduce_points([]) == []
    assert f.reduce_points([[2, None], [4, float('nan')]]) == []


@pytest.mark.asyncio
async def test_shared_cache_and_news_ttl(db, provider):
    device(db, symbols=["AAPL", "MSFT"])
    device(db, "finance-two", ["AAPL"])
    device(db, "finance-off", ["NVDA"], enabled=False)
    await f.refresh_configured(db)
    assert set(provider.calls) == {"AAPL", "MSFT"} and len(provider.calls) == 2
    await f.refresh_configured(db)
    assert len(provider.calls) == 2
    row = db.get(FinanceCache, "finnhub:AAPL")
    row.next_fetch = f.utcnow()-timedelta(seconds=1); db.commit()
    await f.refresh_configured(db)
    assert len(provider.calls) == 3 and provider.headlines == 2


@pytest.mark.asyncio
async def test_failure_keeps_real_quote_timestamp_and_marks_stale(db, provider):
    row = await f.refresh_symbol(db, "AAPL")
    timestamp = row.data["timestamp"]
    row.next_fetch = f.utcnow()-timedelta(seconds=1); db.commit()
    provider.error = f.ProviderError("API-Limit erreicht", "rate_limit", 120)
    row = await f.refresh_symbol(db, "AAPL")
    value = f.public_quote(row, "AAPL")
    assert value["timestamp"] == timestamp and value["price"] == 110
    assert value["stale"] and value["error"] == "API-Limit erreicht"
    assert "meta" not in value and "samples" not in value
    assert f.aware(row.next_fetch) > f.utcnow()+timedelta(seconds=100)


@pytest.mark.parametrize("market,age,expected", [("closed", 800, False), ("closed", 1300, True), ("open", 800, True), ("open", 100, False)])
def test_closed_is_not_technical_failure(db, market, age, expected):
    row = f.cache_row(db, "finnhub", "AAPL")
    row.data = quote(market=market); row.fetched_at = f.utcnow()-timedelta(seconds=age)
    db.commit()
    assert f.public_quote(row, "AAPL")["stale"] == expected


@pytest.mark.asyncio
async def test_finnhub_open_basis_and_real_collected_chart(db, monkeypatch):
    stamp = int(f.utcnow().timestamp()) - 30
    async def request(db, provider, path, params):
        if path == "stock/profile2": return {"country":"US", "name":"Apple Inc.", "currency":"USD"}
        if path == "quote": return {"c":105, "o":100, "h":107, "l":99, "pc":90, "t":stamp}
        if path == "stock/market-status": return {"isOpen":False, "holiday":""}
        raise AssertionError(path)
    monkeypatch.setattr(f, "request", request)
    api = f.FinnhubProvider()
    first = await api.quote(db, "AAPL", {})
    assert first["changePercent"] == pytest.approx(5.0) # not previous close 90
    assert first["points"] == [[stamp, 105.0, 0]]
    assert first["market"] == "closed" and not first["delayed"]
    second = await api.quote(db, "AAPL", first)
    assert second["points"] == first["points"]
    with pytest.raises(f.ProviderError, match="Indizes"):
        await api.quote(db, "^GDAXI", {})


@pytest.mark.asyncio
async def test_missing_key_is_explicit_without_network(db, monkeypatch):
    monkeypatch.setattr(f.settings, "finance_finnhub_key", "")
    row = await f.refresh_symbol(db, "AAPL")
    assert "API-Schlüssel" in row.error
    assert not f.public_quote(row, "AAPL")["available"]


def test_quota_persisted_per_minute_and_day(db):
    for _ in range(8): f.reserve_call(db, "twelve_data")
    with pytest.raises(f.ProviderError, match="Abruflimit"): f.reserve_call(db, "twelve_data")
    row = db.get(FinanceCache, "twelve_data:!budget")
    row.data = {**row.data, "count":0, "daily":800}; db.commit()
    with pytest.raises(f.ProviderError): f.reserve_call(db, "twelve_data")
    row.next_fetch = f.utcnow()+timedelta(minutes=5); db.commit()
    with pytest.raises(f.ProviderError): f.reserve_call(db, "twelve_data")


def test_api_opt_in_order_devices_and_preview(client, db):
    first = device(db, symbols=["MSFT", "AAPL"])
    other = device(db, "finance-two", ["NVDA"])
    off = device(db, "finance-off", ["AAPL"], enabled=False)
    result = client.get(f"/api/v1/devices/{first.device_id}/finance").json()
    assert [q["symbol"] for q in result["securities"]] == ["MSFT", "AAPL"]
    assert client.get(f"/api/v1/devices/{other.device_id}/finance").json()["securities"][0]["symbol"] == "NVDA"
    assert client.get(f"/api/v1/devices/{off.device_id}/finance").status_code == 403
    response = client.get(f"/devices/{first.id}")
    assert response.status_code == 200
    assert 'data-finance-preview' in response.text and 'data-finance-data' in response.text
    assert 'finance-preview.js' in response.text
    assert 'API-Schlüssel werden ausschließlich am Server' in response.text


def test_editor_add_duplicate_move_delete_invalid_and_limit(client, db, provider):
    d = device(db, symbols=["AAPL", "MSFT"])
    url = f"/devices/{d.id}/finance"
    assert client.post(url+"/add", data={"symbol":"aapl"}).status_code == 200
    assert f.symbols_for(d) == ["AAPL", "MSFT"]
    assert client.post(url+"/add", data={"symbol":"NVDA"}).status_code == 200
    assert provider.calls == ["NVDA"]
    assert f.symbols_for(d) == ["AAPL", "MSFT", "NVDA"]
    client.post(url+"/change", data={"symbol":"NVDA", "action":"up"})
    assert f.symbols_for(d) == ["AAPL", "NVDA", "MSFT"]
    client.post(url+"/change", data={"symbol":"NVDA", "action":"delete"})
    assert f.symbols_for(d) == ["AAPL", "MSFT"]
    assert client.post(url+"/add", data={"symbol":"<script>"}).status_code == 422
    page=next(p for p in d.pages if p.page_id == "finance")
    page.settings={"symbols":[f"S{i}" for i in range(48)]};db.commit()
    assert client.post(url+"/add", data={"symbol":"TOOMANY"}).status_code == 422


def test_new_device_finance_disabled(db):
    d = device(db, enabled=False)
    assert not next(p for p in d.pages if p.page_id == "finance").enabled


def test_chart_segments_record_gaps_before_reduction():
    points = [[i*300, 100.0+i%7] for i in range(1, 200)] + [[100000, 100.0]]
    result = f.chart_points(points)
    assert len(result) <= 60
    assert all(p[2] == 0 for p in result[:-1]) and result[-1][2] == 1


@pytest.mark.asyncio
async def test_twelve_data_history_and_quote_fallback(db, monkeypatch):
    stamp = int(f.utcnow().timestamp()) - 30
    fail = False
    async def request(db, provider, path, params):
        if path == "quote":
            return {"close":"105", "open":"100", "high":"106", "low":"99", "timestamp":stamp,
                    "exchange_timezone":"Europe/Berlin", "is_market_open":False, "currency":"EUR", "name":"DAX"}
        if fail: raise f.ProviderError("Historie im Tarif nicht verfügbar", "unsupported")
        assert params["timezone"] == "UTC"
        from datetime import datetime, timezone
        return {"values":[{"datetime":datetime.fromtimestamp(t, timezone.utc).strftime('%Y-%m-%d %H:%M:%S'), "close":str(p)} for t,p in [(stamp-300, 103),(stamp,105)]]}
    monkeypatch.setattr(f, "request", request)
    api = f.TwelveDataProvider()
    q = await api.quote(db, "DAX", {})
    assert q["market"] == "closed" and q["currency"] == "EUR"
    assert q["chartMode"] == "intraday" and len(q["points"]) == 2
    assert q["changePercent"] == pytest.approx(5)
    fail = True
    fallback = await api.quote(db, "DAX", q)
    assert fallback["chartMode"] == "collected" and fallback["price"] == q["price"]
    assert fallback["timestamp"] == stamp and "nicht verfügbar" in fallback["chartError"]


@pytest.mark.asyncio
async def test_http_errors_rate_limit_and_credentials_not_in_url(db, monkeypatch):
    import httpx
    monkeypatch.setattr(f.settings, "finance_finnhub_key", "test-secret-do-not-expose")
    original_client = httpx.AsyncClient
    status = 429
    def handle(request):
        assert request.headers["X-Finnhub-Token"] == "test-secret-do-not-expose"
        assert "test-secret" not in str(request.url)
        return httpx.Response(status, headers={"Retry-After":"120"}, json={"error":"test-secret-do-not-expose"})
    monkeypatch.setattr(f.httpx, "AsyncClient", lambda **kw: original_client(transport=httpx.MockTransport(handle), **kw))
    with pytest.raises(f.ProviderError) as err: await f.request(db,"finnhub","quote",{"symbol":"AAPL"})
    assert err.value.kind == "rate_limit" and "secret" not in str(err.value)
    row = db.get(FinanceCache,"finnhub:!budget")
    assert f.aware(row.next_fetch)>f.utcnow()+timedelta(seconds=100)
    row.next_fetch=None;db.commit();status=403
    with pytest.raises(f.ProviderError) as err: await f.request(db,"finnhub","quote",{"symbol":"AAPL"})
    assert err.value.kind=="unsupported" and "secret" not in str(err.value)
    status=500
    with pytest.raises(f.ProviderError, match="nicht erreichbar"): await f.request(db,"finnhub","quote",{"symbol":"AAPL"})


def test_finance_migration_preserves_existing_settings(db):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    d = device(db, symbols=["AAPL"], enabled=False)
    d.pages=[p for p in d.pages if p.page_id!="finance"]
    d.pages[0].position=42;d.pages[0].settings={"preserve":True};db.commit()
    version=d.config_version
    spec=importlib.util.spec_from_file_location("finance_migration",Path(__file__).parents[1]/"migrations/versions/0019_finance.py")
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    with Operations.context(MigrationContext.configure(db.connection())):
        migration.upgrade()
        migration.upgrade()
    db.expire_all()
    page=next(p for p in d.pages if p.page_id=="finance")
    assert not page.enabled and page.position==43
    assert next(p for p in d.pages if p.page_id=="home").settings=={"preserve":True} and d.config_version>version
