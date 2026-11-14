from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.api.routes import device_or_404
from app.core.database import get_db
from app.models import PodcastEpisode, PodcastProgress
from app.services import podcasts as service

router = APIRouter(prefix='/api/v1/devices/{device_id}/podcasts')

@router.get('/resume')
def resume(device_id: str, db: Session = Depends(get_db)):
    d = device_or_404(device_id, db)
    e = db.get(PodcastEpisode, d.podcast_last.get('episodeId', ''))
    if not e or not e.available or not e.supported: return {'episode': None}
    try: service.authorize(d, e.podcast_id, db)
    except HTTPException: return {'episode': None}
    return {'episode': service.serialize(e, d, db), 'offset': service.episode_index(e, db)}

@router.get('/{podcast_id}/episodes')
def episodes(device_id: str, podcast_id: int, offset: int = Query(0, ge=0), limit: int = Query(12, ge=1, le=20),
             anchor: str = "", direction: int = Query(0, ge=-100000, le=100000), db: Session = Depends(get_db)):
    d = device_or_404(device_id, db); service.authorize(d, podcast_id, db)
    query = select(PodcastEpisode).where(*service.available(podcast_id))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    selected = None
    if anchor:
        e = db.get(PodcastEpisode, anchor)
        if not e or e.podcast_id != podcast_id or not e.available or not e.supported:
            raise HTTPException(404, 'Episode nicht mehr verfügbar')
        selected = max(0, min(total - 1, service.episode_index(e, db) + direction))
        offset = (selected // limit) * limit
    rows = db.scalars(query.order_by(*service.ORDER).offset(offset).limit(limit)).all()
    return {'selectedOffset': selected,'podcastId': podcast_id, 'offset': offset, 'total': total,
            'nextOffset': offset + limit if offset + limit < total else None,
            'episodes': [service.serialize(e, d, db) for e in rows]}

@router.get('/{podcast_id}/episodes/{episode_id}')
def episode(device_id: str, podcast_id: int, episode_id: str, db: Session = Depends(get_db)):
    d = device_or_404(device_id, db); service.authorize(d, podcast_id, db)
    e = db.get(PodcastEpisode, episode_id)
    if not e or e.podcast_id != podcast_id or not e.available or not e.supported: raise HTTPException(404, 'Episode nicht mehr verfügbar')
    return {'episode': service.serialize(e, d, db), 'offset': service.episode_index(e, db)}

@router.get('/{podcast_id}/next')
def next_episode(device_id: str, podcast_id: int, after: str = '', db: Session = Depends(get_db)):
    d = device_or_404(device_id, db); service.authorize(d, podcast_id, db)
    done = select(PodcastProgress.episode_id).where(PodcastProgress.device_id == d.id, PodcastProgress.status == 'completed')
    query = select(PodcastEpisode).where(*service.available(podcast_id), PodcastEpisode.id.not_in(done), PodcastEpisode.id != after)
    anchor = db.get(PodcastEpisode, after)
    e = None
    if anchor and anchor.podcast_id == podcast_id:
        e = db.scalar(query.where((PodcastEpisode.published_at < anchor.published_at) |
            ((PodcastEpisode.published_at == anchor.published_at) & (PodcastEpisode.id < anchor.id))).order_by(*service.ORDER).limit(1))
    if not e: e = db.scalar(query.order_by(*service.ORDER).limit(1))
    return {'episode': service.serialize(e, d, db) if e else None, 'offset': service.episode_index(e, db) if e else 0}

class Progress(BaseModel):
    episodeId: str = Field(min_length=64, max_length=64)
    podcastId: int
    position: int = Field(ge=0, le=7*86400)
    duration: int|None = Field(None, ge=0, le=7*86400)
    status: str = Field(pattern='^(unheard|partial|completed)$')
    revision: int = Field(ge=1, le=2**63-1)
    naturalEnd: bool = False

@router.post('/progress')
def progress(device_id: str, value: Progress, db: Session = Depends(get_db)):
    d = device_or_404(device_id, db); service.authorize(d, value.podcastId, db)
    e = db.get(PodcastEpisode, value.episodeId)
    if not e or e.podcast_id != value.podcastId or not e.available or not e.supported: raise HTTPException(404, 'Episode nicht verfügbar')
    if value.status == 'completed' and not value.naturalEnd:
        raise HTTPException(422, 'Abschluss erfordert reguläres Episodenende')
    p = db.get(PodcastProgress, (d.id, e.id))
    if p is None:
        p = PodcastProgress(device_id=d.id, episode_id=e.id, revision=0)
        db.add(p)
    if value.revision > p.revision:
        p.position, p.duration, p.status = value.position, value.duration or e.duration, value.status
        p.revision, p.updated_at = value.revision, datetime.now(timezone.utc)
        if value.revision > d.podcast_last.get('revision', 0):
            d.podcast_last = {'podcastId': e.podcast_id, 'episodeId': e.id, 'revision': value.revision}
        db.commit()
    return {'ok': True, 'episodeId': e.id, 'revision': p.revision}
