"""Provider-neutral finance cache. Only scheduler/admin actions contact providers.

No unofficial endpoints or HTML scraping. Prices and timestamps always originate
with the provider; Finnhub's free fallback chart contains collected quotes only.
"""
import asyncio
import copy
import math
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Protocol
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from app.core.config import settings
from app.models import Device, FinanceCache

MAX_SYMBOLS = 48
MAX_GLOBAL_SYMBOLS = 256
MAX_POINTS = 60
_lock = asyncio.Lock()


def utcnow():
    return datetime.now(timezone.utc)


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def normalize_symbol(value):
    value = value.strip().upper()
    if not re.fullmatch(r"[A-Z0-9^][A-Z0-9.^:/_-]{0,31}", value):
        raise ValueError("Ungültiges Symbol: maximal 32 Buchstaben, Ziffern und . ^ : / _ -")
    return value


def symbols_for(device):
    page = next((p for p in device.pages if p.page_id == "finance"), None)
    return list((page.settings or {}).get("symbols", []))[:MAX_SYMBOLS] if page else []


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) and result > 0 else None
    except (ValueError, TypeError):
        return None


def reduce_points(points, limit=MAX_POINTS):
    """Keep first/last and extrema per time bucket, retaining real timestamps/gaps."""
    points = sorted({int(t): float(p) for t, p in points if number(p) and int(t) > 0}.items())
    if len(points) <= limit:
        return [list(p) for p in points]
    chosen = [points[0]]
    interior = points[1:-1]
    buckets = (limit - 2) // 2
    for i in range(buckets):
        bucket = interior[i * len(interior) // buckets:(i + 1) * len(interior) // buckets]
        chosen.extend(sorted({min(bucket, key=lambda x: x[1]), max(bucket, key=lambda x: x[1])}))
    chosen.append(points[-1])
    return [list(p) for p in sorted(set(chosen))]


def chart_points(points):
    # Segment IDs originate before downsampling: thinning is not a data gap.
    raw = reduce_points(points, max(len(points), 2))
    segments = {}; segment = 0; previous = 0
    for t, value in raw:
        if previous and t - previous > 900: segment += 1
        segments[t] = segment; previous = t
    return [[t, value, segments[t]] for t, value in reduce_points(raw)]


class ProviderError(Exception):
    def __init__(self, message, kind="unavailable", retry=900):
        super().__init__(message)
        self.kind, self.retry = kind, retry


class FinanceProvider(Protocol):
    name: str
    async def quote(self, db, symbol: str, previous: dict) -> dict: ...
    async def news(self, db, symbol: str, quote: dict) -> dict | None: ...


def cache_row(db, provider, symbol):
    row = db.get(FinanceCache, f"{provider}:{symbol}")
    if row is None:
        row = FinanceCache(key=f"{provider}:{symbol}", provider=provider, symbol=symbol, data={})
        db.add(row)
        db.flush()
    return row


def reserve_call(db, provider):
    """Persist quota before each request, including failures and metadata calls."""
    now = utcnow()
    row = cache_row(db, provider, "!budget")
    data = dict(row.data or {})
    if aware(row.next_fetch) and aware(row.next_fetch) > now:
        raise ProviderError("API-Limit: nächster Abruf später", "rate_limit")
    day, minute = now.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%dT%H:%M")
    if data.get("day") != day:
        data.update(day=day, daily=0)
    if data.get("minute") != minute:
        data.update(minute=minute, count=0)
    per_minute = 50 if provider == "finnhub" else 8
    per_day = 0 if provider == "finnhub" else 800
    if data.get("count", 0) >= per_minute or (per_day and data.get("daily", 0) >= per_day):
        raise ProviderError("Kostenloses API-Abruflimit erreicht", "rate_limit", 60)
    data["count"] = data.get("count", 0) + 1
    data["daily"] = data.get("daily", 0) + 1
    row.data = data
    db.commit()


async def request(db, provider, path, params):
    key = settings.finance_finnhub_key if provider == "finnhub" else settings.finance_twelve_data_key
    if not key:
        raise ProviderError("API-Schlüssel am Homeserver fehlt", "configuration", 300)
    reserve_call(db, provider)
    base = "https://finnhub.io/api/v1/" if provider == "finnhub" else "https://api.twelvedata.com/"
    headers = {"X-Finnhub-Token": key} if provider == "finnhub" else {"Authorization": "apikey " + key}
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout, follow_redirects=False) as client:
            async with client.stream("GET", base + path, params=params, headers=headers) as response:
                if response.status_code == 429:
                    try: retry = max(60, min(86400, int(response.headers.get("Retry-After", "900"))))
                    except ValueError: retry = 900
                    row = cache_row(db, provider, "!budget")
                    row.next_fetch = utcnow() + timedelta(seconds=retry)
                    db.commit()
                    raise ProviderError("API-Limit erreicht; Abruf pausiert", "rate_limit", retry)
                if response.status_code in {401, 403}:
                    raise ProviderError("Symbol oder Endpunkt für diesen API-Zugang nicht freigegeben", "unsupported", 21600)
                response.raise_for_status()
                raw = bytearray()
                async for part in response.aiter_bytes():
                    raw.extend(part)
                    if len(raw) > 1_000_000:
                        raise ProviderError("Finanzdaten-Antwort zu groß")
                import json
                value = json.loads(raw)
    except (httpx.HTTPError, ValueError):
        # Never include URLs, API credentials or provider response bodies in errors.
        raise ProviderError("Finanzdienst derzeit nicht erreichbar") from None
    if isinstance(value, dict) and (value.get("error") or value.get("status") == "error"):
        code = value.get("code")
        if code == 429:
            row = cache_row(db, provider, "!budget")
            row.next_fetch = utcnow() + timedelta(minutes=15)
            db.commit()
            raise ProviderError("API-Limit erreicht; Abruf pausiert", "rate_limit")
        raise ProviderError("Symbol ungültig oder im API-Tarif nicht verfügbar", "unsupported", 21600)
    return value


class FinnhubProvider:
    name = "finnhub"

    async def market(self, db):
        row = cache_row(db, self.name, "!market-US")
        if not row.fetched_at or utcnow() - aware(row.fetched_at) >= timedelta(minutes=5):
            try:
                value = await request(db, self.name, "stock/market-status", {"exchange": "US"})
                if not isinstance(value, dict): raise ProviderError("Ungültiger Marktstatus")
                row.data = value
                row.fetched_at = utcnow()
                db.commit()
            except ProviderError:
                return "unknown"
        return "open" if row.data.get("isOpen") is True else "closed" if row.data.get("isOpen") is False else "unknown"

    async def quote(self, db, symbol, previous):
        if symbol.startswith("^"):
            raise ProviderError("Indizes sind im kostenlosen Finnhub-Zugang nicht verfügbar (kein ETF-Ersatz)", "unsupported", 21600)
        meta = previous.get("meta")
        if not meta:
            profile = await request(db, self.name, "stock/profile2", {"symbol": symbol})
            if not isinstance(profile, dict) or not profile or profile.get("country") != "US" or not profile.get("currency"):
                raise ProviderError("Kein unterstützter US-Aktientitel; internationaler Markt im kostenlosen Zugang nicht verfügbar", "unsupported", 21600)
            meta = {"name": str(profile.get("name", symbol))[:100], "currency": profile["currency"], "timezone": "America/New_York"}
        q = await request(db, self.name, "quote", {"symbol": symbol})
        if not isinstance(q, dict): raise ProviderError("Ungültige Kursantwort")
        price, opening = number(q.get("c")), number(q.get("o"))
        timestamp = int(q.get("t") or 0)
        if not price or timestamp <= 0 or timestamp > utcnow().timestamp() + 60:
            raise ProviderError("Kein gültiger Kurs für dieses Symbol verfügbar", "unsupported", 21600)
        session = datetime.fromtimestamp(timestamp, ZoneInfo(meta["timezone"])).date().isoformat()
        points = previous.get("samples", previous.get("points", [])) if previous.get("session") == session else []
        points = [p for p in points if p[0] != timestamp] + [[timestamp, price]]
        points = sorted(points)[-400:]
        market = await self.market(db)
        return {"symbol": symbol, "name": meta["name"], "currency": meta["currency"], "timestamp": timestamp,
                "price": price, "open": opening, "high": number(q.get("h")), "low": number(q.get("l")),
                "changePercent": (price / opening - 1) * 100 if opening else None,
                "session": session, "timezone": meta["timezone"], "market": market,
                "delayed": market == "open" and utcnow().timestamp() - timestamp > 900,
                "points": chart_points(points), "samples": points, "meta": meta,
                "chartMode": "collected", "gapSeconds": 900, "provider": self.name}

    async def news(self, db, symbol, quote):
        today = utcnow().date()
        rows = await request(db, self.name, "company-news", {"symbol": symbol, "from": (today-timedelta(days=7)).isoformat(), "to": today.isoformat()})
        if not isinstance(rows, list): raise ProviderError("Ungültige Nachrichtenantwort")
        rows = [r for r in rows if isinstance(r, dict) and r.get("headline") and r.get("datetime") and symbol in {s.strip() for s in str(r.get("related", "")).split(",")}]
        if not rows: return None
        r = max(rows, key=lambda r: int(r["datetime"]))
        return {"title": str(r["headline"])[:300], "source": str(r.get("source", ""))[:60], "timestamp": int(r["datetime"])}


class TwelveDataProvider:
    """Optional entitled API access; Basic does not grant general display rights."""
    name = "twelve_data"

    async def quote(self, db, symbol, previous):
        native = previous.get("nativeSymbol", symbol)
        if symbol.startswith("^") and not previous.get("nativeSymbol"):
            names = {"^GDAXI": "DAX", "^GSPC": "S&P 500", "^IXIC": "NASDAQ Composite"}
            if symbol not in names:
                raise ProviderError("Unbekanntes Indexkürzel: natives Anbietersymbol verwenden", "unsupported", 21600)
            search = await request(db, self.name, "symbol_search", {"symbol": names[symbol], "outputsize": 30})
            if not isinstance(search, dict): raise ProviderError("Ungültige Symbolsuche")
            matches = [r for r in search.get("data", []) if r.get("instrument_type", "").lower() == "index" and r.get("instrument_name", "").casefold() == names[symbol].casefold()]
            if len(matches) != 1:
                raise ProviderError("Index nicht eindeutig auflösbar: natives Anbietersymbol verwenden", "unsupported", 21600)
            native = matches[0]["symbol"]
        q = await request(db, self.name, "quote", {"symbol": native})
        if not isinstance(q, dict): raise ProviderError("Ungültige Kursantwort")
        chart_error = None
        try:
            series = await request(db, self.name, "time_series", {"symbol": native, "interval": "5min", "outputsize": 500, "timezone": "UTC", "order": "ASC"})
            if not isinstance(series, dict): raise ProviderError("Ungültige Intraday-Antwort")
        except ProviderError:
            series = {}
            chart_error = "Intraday-Historie nicht verfügbar; nur gesammelte Kurse"
        price, opening = number(q.get("close")), number(q.get("open"))
        stamp = int(q.get("timestamp") or 0)
        zone = q.get("exchange_timezone") or series.get("meta", {}).get("exchange_timezone")
        if not price or not stamp or stamp > utcnow().timestamp() + 60 or not zone:
            raise ProviderError("Unvollständige Finanzdaten")
        localzone = ZoneInfo(zone)
        session = datetime.fromtimestamp(stamp, localzone).date().isoformat()
        points = []
        for row in series.get("values", []):
            t = int(datetime.fromisoformat(row["datetime"]).replace(tzinfo=timezone.utc).timestamp())
            if t <= stamp and datetime.fromtimestamp(t, localzone).date().isoformat() == session and number(row.get("close")):
                points.append([t, float(row["close"])])
        if not points:
            points = [[p[0], p[1]] for p in previous.get("samples", previous.get("points", []))] if previous.get("session") == session else []
            points = [p for p in points if p[0] != stamp] + [[stamp, price]]
            points = sorted(points)[-400:]
            chart_error = chart_error or "Intraday-Historie fehlt; nur gesammelte Kurse"
        market = "open" if q.get("is_market_open") is True else "closed" if q.get("is_market_open") is False else "unknown"
        return {"symbol": symbol, "nativeSymbol": native, "name": str(q.get("name", symbol))[:100], "price": price,
                "currency": str(q.get("currency", ""))[:8], "timestamp": stamp, "open": opening,
                "high": number(q.get("high")), "low": number(q.get("low")), "changePercent": (price/opening-1)*100 if opening else None,
                "session": session, "timezone": zone, "market": market,
                "delayed": market == "open" and utcnow().timestamp()-stamp > 900,
                "points": chart_points(points), "samples": points, "chartMode": "collected" if chart_error else "intraday",
                "chartError": chart_error, "gapSeconds": 900, "provider": self.name}

    async def news(self, db, symbol, quote):
        # No symbol-only web searches: ambiguous ticker matches are avoided.
        return None


PROVIDERS = {"finnhub": FinnhubProvider(), "twelve_data": TwelveDataProvider()}


def provider():
    if settings.finance_provider not in PROVIDERS:
        raise ProviderError("Unbekannter Finanzdatenanbieter", "configuration", 300)
    return PROVIDERS[settings.finance_provider]


async def refresh_symbol(db, symbol):
    api = provider()
    row = cache_row(db, api.name, symbol)
    now = utcnow()
    if row.next_fetch and aware(row.next_fetch) > now:
        return row
    try:
        data = await api.quote(db, symbol, row.data or {})
        if data.get("timestamp", 0) < (row.data or {}).get("timestamp", 0):
            raise ProviderError("Anbieter liefert einen älteren Kurs; letzter Cache bleibt erhalten")
        news_at, news_error = row.news_at, row.news_error
        # Preserve headline if only its source is temporarily unavailable.
        data["news"] = (row.data or {}).get("news")
        if not row.news_at or now - aware(row.news_at) >= timedelta(hours=1):
            try:
                data["news"] = await api.news(db, symbol, data)
                news_error = None
            except ProviderError:
                news_error = "Nachrichtenabruf derzeit nicht verfügbar"
            news_at = now
        # Quota reservations may commit during HTTP work; publish the complete
        # result only after all awaits, without advancing old quote freshness.
        row.fetched_at = now
        row.error = None
        row.news_at, row.news_error = news_at, news_error
        row.data = data
        row.next_fetch = now + timedelta(minutes=15 if data["market"] == "closed" else 5)
    except ProviderError as error:
        row.error = str(error)
        row.next_fetch = now + timedelta(seconds=error.retry)
    except (ValueError, KeyError, TypeError, OverflowError):
        row.error = "Unvollständige oder ungültige Anbieterantwort"
        row.next_fetch = now + timedelta(minutes=15)
    db.commit()
    return row


async def refresh_configured(db):
    async with _lock:
        symbols = set()
        for device in db.scalars(select(Device).where(Device.enabled.is_(True))):
            if any(p.page_id == "finance" and p.enabled for p in device.pages):
                symbols.update(symbols_for(device))
        # Earliest due first: large lists cannot starve the same trailing symbols.
        name = settings.finance_provider
        def due(s):
            row = db.get(FinanceCache, f"{name}:{s}")
            return aware(row.next_fetch) if row and row.next_fetch else datetime.min.replace(tzinfo=timezone.utc)
        started = time.monotonic()
        for symbol in sorted(symbols, key=due)[:MAX_GLOBAL_SYMBOLS]:
            if time.monotonic() - started > 45:
                break  # Bound outage work; due ordering continues next cycle.
            try: await refresh_symbol(db, symbol)
            except ProviderError: break


def public_quote(row, symbol):
    if not row or not row.data.get("timestamp"):
        return {"symbol": symbol, "available": False, "stale": True, "error": row.error if row else "Wartet auf ersten Abruf", "points": []}
    data = copy.deepcopy(row.data)
    for field in ("samples", "meta", "nativeSymbol"):
        data.pop(field, None)
    now = utcnow()
    fetched_age = (now - aware(row.fetched_at)).total_seconds() if row.fetched_at else 1e9
    stale = bool(row.error) or fetched_age > (1200 if data.get("market") == "closed" else 600)
    # A closed market alone is not an error; do flag a quote from an older session
    # when a market that has opened again is no longer delivering usable prices.
    quote_age = now.timestamp() - data["timestamp"]
    if quote_age > 7 * 86400 or (data.get("market") == "open" and quote_age > 3600):
        stale = True
    data.update(available=True, stale=stale, error=row.error, fetchedAt=int(aware(row.fetched_at).timestamp()) if row.fetched_at else 0,
                newsStale=bool(row.news_error) or not row.news_at or (now-aware(row.news_at)).total_seconds()>7200)
    localzone = ZoneInfo(data.get("timezone", "UTC"))
    data["quoteTime"] = datetime.fromtimestamp(data["timestamp"], localzone).strftime("%d.%m. %H:%M")
    if data.get("news"):
        data["news"]["time"] = datetime.fromtimestamp(data["news"]["timestamp"], localzone).strftime("%d.%m. %H:%M")
    return data


def data_for_device(device, db):
    rows = [public_quote(db.get(FinanceCache, f"{settings.finance_provider}:{s}"), s) for s in symbols_for(device)]
    return {"schemaVersion": 1, "generatedAt": int(utcnow().timestamp()), "securities": rows}
