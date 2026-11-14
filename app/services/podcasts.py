"""RSS metadata only; audio streams directly from the publisher to LEAP."""
import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlsplit, urlunsplit
import feedparser
import httpx
from fastapi import HTTPException
from sqlalchemy import func, select
from app.core.config import settings
from app.core.security import validate_external_url
from app.models import Device, Podcast, PodcastEpisode, PodcastProgress
from app.services.feeds import clean_text, parse_date

MAX_CHANNELS = 32
MAX_FEED_BYTES = 8 * 1024 * 1024
ORDER = (PodcastEpisode.published_at.desc(), PodcastEpisode.id.desc())

def validate(name, url, position):
    name, url = name.strip(), url.strip()
    try:
        p = urlsplit(url)
        valid = p.scheme in {'http', 'https'} and p.hostname and not p.username and not p.password and not p.fragment
        p.port
    except ValueError:
        valid = False
    if (not valid or not name or len(name.encode()) > 120 or len(url.encode()) > 1000 or
        any(ord(c) <= 32 or ord(c) == 127 or c == '\\' for c in url) or '#' in url or
        any(ord(c) < 32 for c in name) or not 1 <= position <= 9999):
        raise HTTPException(422, 'Name, HTTP(S)-Feed-URL und Reihenfolge prüfen')
    return name, urlunsplit(p)

def channels(db):
    return db.scalars(select(Podcast).order_by(Podcast.position, Podcast.id)).all()

def available(podcast_id):
    return (PodcastEpisode.podcast_id == podcast_id, PodcastEpisode.available.is_(True), PodcastEpisode.supported.is_(True))

def for_device(device, db):
    if not any(p.page_id == 'podcasts' and p.enabled for p in device.pages):
        return []
    counts = dict(db.execute(select(PodcastEpisode.podcast_id, func.count()).where(
        PodcastEpisode.available.is_(True), PodcastEpisode.supported.is_(True)).group_by(PodcastEpisode.podcast_id)).all())
    return [{'id': p.id, 'name': p.name, 'episodeCount': counts.get(p.id, 0)}
            for p in channels(db) if p.enabled and p.id in (device.podcast_ids or [])]

def authorize(device, podcast_id, db):
    p = db.get(Podcast, podcast_id)
    if (not p or not p.enabled or podcast_id not in (device.podcast_ids or []) or
        not any(page.page_id == 'podcasts' and page.enabled for page in device.pages)):
        raise HTTPException(404, 'Podcast nicht freigegeben')
    return p

def bump_assigned(db, podcast_id, delete=False):
    for d in db.scalars(select(Device)).all():
        if podcast_id in (d.podcast_ids or []):
            d.config_version += 1
            if delete:
                d.podcast_ids = [x for x in d.podcast_ids if x != podcast_id]
            if d.podcast_last.get('podcastId') == podcast_id and delete:
                d.podcast_last = {}

def duration(value):
    try:
        parts = str(value).strip().split(':')
        if not 1 <= len(parts) <= 3: return None
        result = 0
        for part in parts:
            number = float(part)
            if number < 0: return None
            result = result * 60 + number
        return int(result) if 0 < result <= 7 * 86400 else None
    except (ValueError, TypeError, OverflowError):
        return None

def parse(content, podcast, db, feed_url=None):
    parsed = feedparser.parse(content)
    if not parsed.version or (parsed.bozo and not parsed.entries):
        raise ValueError('Ungültiger RSS-/Atom-Feed')
    seen, urls = set(), set()
    existing = {e.external_id: e for e in db.scalars(select(PodcastEpisode).where(PodcastEpisode.podcast_id == podcast.id))}
    for entry in parsed.entries:
        enclosures = entry.get('enclosures', []) or [x for x in entry.get('links', []) if x.get('rel') == 'enclosure']
        candidates = []
        for item in enclosures:
            url = urljoin(feed_url or podcast.url, item.get('href', ''))
            mime = item.get('type', '').split(';')[0].strip().lower()
            try: validate('Episode', url, 1)
            except HTTPException: continue
            extension = urlsplit(url).path.lower()
            mp3 = mime in {'audio/mpeg', 'audio/mp3', 'audio/x-mpeg'} or (mime in {'', 'application/octet-stream'} and extension.endswith('.mp3'))
            candidates.append((mp3, url, mime))
        if not candidates: continue
        supported, url, mime = sorted(candidates, key=lambda x: not x[0])[0]
        # GUID is authoritative, enclosure URL is the stable fallback.
        external = str(entry.get('id') or entry.get('guid') or url)
        if external in seen or url in urls: continue
        seen.add(external); urls.add(url)
        episode = existing.get(external)
        if not episode:
            episode = PodcastEpisode(id=hashlib.sha256(f'{podcast.id}|{external}'.encode()).hexdigest(), podcast_id=podcast.id, external_id=external)
            db.add(episode)
        episode.title = clean_text(entry.get('title') or 'Ohne Titel')[:500]
        episode.description = clean_text(entry.get('summary', ''))[:10000]
        # Undated entries retain their first import date for stable pagination.
        if entry.get('published') or entry.get('updated') or not episode.published_at:
            episode.published_at = parse_date(entry)
        episode.duration = duration(entry.get('itunes_duration'))
        episode.url, episode.mime_type, episode.supported, episode.available = url, mime[:100], supported, True
    for external, episode in existing.items():
        episode.available = external in seen
    db.flush()
    return len(seen)

async def fetch(podcast, db):
    podcast.last_fetch = datetime.now(timezone.utc)
    try:
        url = podcast.url
        async with httpx.AsyncClient(timeout=settings.request_timeout, follow_redirects=False) as client:
            for redirect in range(6):
                # Apply existing private-feed policy on every redirect, outside the event loop.
                await asyncio.to_thread(validate_external_url, url)
                async with client.stream('GET', url, headers={'User-Agent': 'LEAP-HomeServer/1.7'}) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        if redirect == 5 or not response.headers.get('location'): raise ValueError('Zu viele/ungültige Weiterleitungen')
                        url = urljoin(url, response.headers['location'])
                        continue
                    response.raise_for_status()
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_FEED_BYTES: raise ValueError('Feed ist zu groß (max. 8 MiB)')
                    # Savepoint protects the old catalog on malformed imports.
                    with db.begin_nested(): parse(bytes(data), podcast, db, url)
                    podcast.last_success = datetime.now(timezone.utc)
                    podcast.last_error = None
                    bump_assigned(db, podcast.id)
                    db.commit()
                    return True
        raise ValueError('Feed konnte nicht geladen werden')
    except Exception as exc:
        podcast.last_error = str(exc)[:1000]
        db.commit()
        return False

async def refresh_due(db):
    now = datetime.now(timezone.utc)
    for p in channels(db):
        last = p.last_fetch.replace(tzinfo=timezone.utc) if p.last_fetch else None
        if p.enabled and (not last or last < now - timedelta(hours=3)):
            await fetch(p, db)

def serialize(episode, device, db):
    progress = db.get(PodcastProgress, (device.id, episode.id))
    return {'id': episode.id, 'podcastId': episode.podcast_id, 'title': episode.title,
            'url': episode.url, 'publishedAt': episode.published_at,
            'duration': (progress.duration if progress and progress.duration else episode.duration),
            'position': progress.position if progress else 0,
            'status': progress.status if progress else 'unheard',
            'revision': progress.revision if progress else 0}

def episode_index(episode, db):
    return db.scalar(select(func.count()).select_from(PodcastEpisode).where(*available(episode.podcast_id),
        (PodcastEpisode.published_at > episode.published_at) |
        ((PodcastEpisode.published_at == episode.published_at) & (PodcastEpisode.id > episode.id))))
