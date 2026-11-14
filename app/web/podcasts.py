from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models import Podcast, PodcastEpisode
from app.services import podcasts as service
from app.web.routes import redir, templates

router = APIRouter()

def get(id, db):
    p = db.get(Podcast, id)
    if not p: raise HTTPException(404, 'Podcast nicht gefunden')
    return p

def unique(url, db, id=None):
    if db.scalar(select(Podcast).where(Podcast.url == url, Podcast.id != id if id else True)):
        raise HTTPException(409, 'Feed-URL bereits vorhanden')

@router.get('/podcasts', response_class=HTMLResponse)
def channels(request: Request, db: Session = Depends(get_db)):
    counts = dict(db.execute(select(PodcastEpisode.podcast_id, func.count()).where(
        PodcastEpisode.available.is_(True), PodcastEpisode.supported.is_(True)).group_by(PodcastEpisode.podcast_id)).all())
    return templates.TemplateResponse(request, 'podcasts.html', {'podcasts': service.channels(db), 'counts': counts})

@router.post('/podcasts')
async def add(name: str = Form(), url: str = Form(), position: int = Form(1), enabled: bool = Form(False), db: Session = Depends(get_db)):
    name, url = service.validate(name, url, position); unique(url, db)
    p = Podcast(name=name, url=url, position=position, enabled=enabled)
    db.add(p); db.commit()
    await service.fetch(p, db)
    return redir('/podcasts')

@router.post('/podcasts/{id}')
def update(id: int, name: str = Form(), url: str = Form(), position: int = Form(1), enabled: bool = Form(False), db: Session = Depends(get_db)):
    p = get(id, db); name, url = service.validate(name, url, position); unique(url, db, id)
    if p.url != url: p.last_fetch = None
    p.name, p.url, p.position, p.enabled = name, url, position, enabled
    service.bump_assigned(db, id); db.commit()
    return redir('/podcasts')

@router.post('/podcasts/{id}/fetch')
async def refresh(id: int, db: Session = Depends(get_db)):
    await service.fetch(get(id, db), db)
    return redir('/podcasts')

@router.post('/podcasts/{id}/delete')
def delete(id: int, db: Session = Depends(get_db)):
    p = get(id, db); service.bump_assigned(db, id, delete=True)
    db.delete(p); db.commit()
    return redir('/podcasts')

@router.get('/podcasts/{id}/episodes', response_class=HTMLResponse)
def episodes(id: int, request: Request, offset: int = 0, db: Session = Depends(get_db)):
    p = get(id, db); offset = max(0, offset)
    rows = db.scalars(select(PodcastEpisode).where(PodcastEpisode.podcast_id == id).order_by(*service.ORDER).offset(offset).limit(50)).all()
    total = db.scalar(select(func.count()).select_from(PodcastEpisode).where(PodcastEpisode.podcast_id == id))
    return templates.TemplateResponse(request, 'podcast_episodes.html', {'podcast': p, 'episodes': rows, 'offset': offset, 'total': total})
