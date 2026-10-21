from datetime import datetime, timezone
import pytest
from app.models import Device
from app.services.devices import initialize_pages
from app.services import finance as f

STAMP=int(datetime(2026,10,21,10,0,tzinfo=timezone.utc).timestamp())

def response(symbol='CJ6.F', currency='EUR', exchange='FRA'):
    return {'chart':{'result':[{'meta':{'symbol':symbol,'currency':currency,'exchangeName':exchange,
        'exchangeTimezoneName':'Europe/Berlin','regularMarketPrice':80,'regularMarketTime':STAMP,
        'regularMarketDayHigh':81,'regularMarketDayLow':77,
        'currentTradingPeriod':{'regular':{'start':STAMP-3600,'end':STAMP+3600}}},
        'timestamp':[STAMP-600,STAMP-300,STAMP],
        'indicators':{'quote':[{'open':[78,79,80],'close':[78,None,80]}]}}]}}

@pytest.mark.asyncio
async def test_german_quotes_isolated_from_us(db, monkeypatch):
    monkeypatch.setattr(f,'utcnow',lambda: datetime.fromtimestamp(STAMP+900,timezone.utc))
    calls=[]
    async def source(db,symbol): calls.append(symbol); return response(symbol)
    monkeypatch.setattr(f,'yahoo_chart',source)
    monkeypatch.setattr(f.settings,'finance_provider','finnhub')
    d=Device(device_id='eur',name='EUR');initialize_pages(d)
    next(p for p in d.pages if p.page_id=='finance').settings={'symbols':['YAHOO:CJ6.F','YAHOO:6RJ0.F']}
    db.add(d);db.commit()
    for symbol in f.symbols_for(d):
        row=await f.refresh_symbol(db,symbol)
        assert not row.error
        assert row.data['currency']=='EUR' and row.data['exchange']=='Frankfurt'
        assert row.data['open']==78 and row.data['timestamp']==STAMP
        assert row.data['delayed'] is True
        assert len(row.data['points'])==2
    quotes=f.data_for_device(d,db)['securities']
    assert [q['displaySymbol'] for q in quotes]==['CJ6.F','6RJ0.F']
    assert calls==['CJ6.F','6RJ0.F']
    assert not any(q['stale'] for q in quotes)
    assert 'samples' not in quotes[0]
    assert f.provider_for_symbol('RKLB').name=='finnhub'

@pytest.mark.asyncio
@pytest.mark.parametrize('currency,exchange', [('USD','FRA'),('EUR','NMS'),('CAD','TOR')])
async def test_reject_wrong_market_currency(db,monkeypatch,currency,exchange):
    async def source(db,symbol): return response(symbol,currency,exchange)
    monkeypatch.setattr(f,'yahoo_chart',source)
    row=await f.refresh_symbol(db,'YAHOO:CJ6.F')
    assert row.error and not row.data.get('timestamp')

@pytest.mark.asyncio
async def test_failure_keeps_quote_and_time(db,monkeypatch):
    monkeypatch.setattr(f,'utcnow',lambda: datetime.fromtimestamp(STAMP+900,timezone.utc))
    async def source(db,symbol): return response(symbol)
    monkeypatch.setattr(f,'yahoo_chart',source)
    row=await f.refresh_symbol(db,'YAHOO:CJ6.F')
    async def fail(db,symbol): raise f.ProviderError('Unavailable')
    monkeypatch.setattr(f,'yahoo_chart',fail)
    row=await f.refresh_symbol(db,'YAHOO:CJ6.F',force=True)
    public=f.public_quote(row,'YAHOO:CJ6.F')
    assert public['stale'] and public['timestamp']==STAMP and public['price']==80

@pytest.mark.asyncio
async def test_missing_points_does_not_invent_history(db,monkeypatch):
    monkeypatch.setattr(f,'utcnow',lambda: datetime.fromtimestamp(STAMP+900,timezone.utc))
    async def source(db,symbol):
        data=response(symbol);data['chart']['result'][0]['indicators']={};return data
    monkeypatch.setattr(f,'yahoo_chart',source)
    row=await f.refresh_symbol(db,'YAHOO:6RJ0.F')
    assert row.data['chartMode']=='collected'
    assert row.data['open'] is None and row.data['changePercent'] is None
    assert row.data['points']==[[STAMP,80,0]]

@pytest.mark.asyncio
async def test_yahoo_rate_limit_is_persistent_and_no_login_retry(db,monkeypatch):
    import httpx
    original=httpx.AsyncClient
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(429,request=request)
    monkeypatch.setattr(f.httpx,'AsyncClient',lambda **kw: original(transport=httpx.MockTransport(handler),**kw))
    with pytest.raises(f.ProviderError, match='Abruflimit'):
        await f.yahoo_chart(db,'CJ6.F')
    with pytest.raises(f.ProviderError, match='API-Limit'):
        await f.yahoo_chart(db,'CJ6.F')
    assert len(calls)==1
    assert 'api_token' not in str(calls[0].url) and 'cookie' not in calls[0].headers
