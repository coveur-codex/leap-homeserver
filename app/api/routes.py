from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models import Article, Device, Feed, QuizQuestion
from app.services.weather import get_weather
router=APIRouter(prefix="/api/v1")
def device_or_404(device_id:str,db:Session)->Device:
    d=db.scalar(select(Device).where(Device.device_id==device_id,Device.enabled==True))
    if not d: raise HTTPException(404,"Gerät nicht gefunden")
    return d
class Checkin(BaseModel):
    firmwareVersion:str|None=None; battery:int|None=Field(None,ge=0,le=100); wifiRssi:int|None=None; freeFlash:int|None=None
@router.get("/devices/{device_id}/config")
def config(device_id:str,db:Session=Depends(get_db)):
    d=device_or_404(device_id,db)
    return {"deviceId":d.device_id,"configVersion":d.config_version,"name":d.name,"childName":d.child_name,"age":d.age,"avatar":d.avatar,"avatarConfig":d.avatar_config,"pages":[{"id":p.page_id,"title":p.title,"enabled":p.enabled,"order":p.position,"settings":p.settings} for p in d.pages],"games":[{"id":x,"enabled":True} for x in ("hot_potato","simon_motion","tilt_maze")],"homeSlots":d.home_slots}
@router.get("/devices/{device_id}/version")
def version(device_id:str,db:Session=Depends(get_db)):
    d=device_or_404(device_id,db); return {"configVersion":d.config_version,"contentVersion":max(d.news_version,d.weather_version,d.quiz_version)}
@router.get("/devices/{device_id}/sync")
def sync(device_id:str,db:Session=Depends(get_db)):
    d=device_or_404(device_id,db); return {"configVersion":d.config_version,"newsVersion":d.news_version,"weatherVersion":d.weather_version,"quizVersion":d.quiz_version}
@router.post("/devices/{device_id}/checkin")
def checkin(device_id:str,data:Checkin,db:Session=Depends(get_db)):
    d=device_or_404(device_id,db); d.last_seen=datetime.now(timezone.utc); d.firmware_version=data.firmwareVersion; d.battery=data.battery; d.wifi_rssi=data.wifiRssi; d.free_flash=data.freeFlash; db.commit(); return {"ok":True,"serverTime":d.last_seen}
@router.get("/devices/{device_id}/news")
def news(device_id:str,limit:int|None=Query(None,ge=1,le=100),since:datetime|None=None,db:Session=Depends(get_db)):
    d=device_or_404(device_id,db); wanted={c.slug for c in d.categories}; include=set(d.included_feed_ids); exclude=set(d.excluded_feed_ids)
    cutoff=max(since or datetime.min.replace(tzinfo=timezone.utc),datetime.now(timezone.utc)-timedelta(hours=d.news_max_age_hours))
    q=select(Article).join(Feed).where(Article.published_at>=cutoff,~Article.feed_id.in_(exclude)).order_by(Article.published_at.desc())
    rows=[a for a in db.scalars(q).all() if a.category in wanted or a.feed_id in include][:(limit or d.news_limit)]
    return {"version":d.news_version,"articles":[{"id":f"news_{a.id}","category":a.category,"title":a.title,"summary":a.summary,"source":a.source,"published":a.published_at,"image":f"/api/v1/assets/news/{a.id}/thumb.jpg" if a.image_leap else None} for a in rows]}
@router.get("/devices/{device_id}/weather")
async def weather(device_id:str,db:Session=Depends(get_db)):
    d=device_or_404(device_id,db)
    try:return await get_weather(d,db)
    except ValueError as e: raise HTTPException(422,str(e))
    except Exception as e: raise HTTPException(503,"Wetterdienst derzeit nicht verfügbar")
@router.get("/devices/{device_id}/quiz")
def quiz(device_id:str,db:Session=Depends(get_db)):
    d=device_or_404(device_id,db); catalog_ids=[c.id for c in d.quiz_catalogs if c.enabled]
    rows=db.scalars(select(QuizQuestion).where(QuizQuestion.catalog_id.in_(catalog_ids),QuizQuestion.min_age<=d.age)).all() if catalog_ids else []
    return {"version":d.quiz_version,"questions":[{"id":q.id,"q":q.question,"a":q.answers,"explanation":q.explanation,"minAge":q.min_age,"difficulty":q.difficulty,"tags":q.tags} for q in rows]}
@router.get("/assets/news/{article_id}/{variant}.jpg")
def asset(article_id:int,variant:str):
    if variant not in {"thumb","hero"}: raise HTTPException(404)
    from app.core.config import settings
    path=settings.data_dir/"images"/"news"/str(article_id)/f"{variant}.jpg"
    if not path.is_file(): raise HTTPException(404)
    return FileResponse(path,media_type="image/jpeg",headers={"Cache-Control":"public, max-age=86400, immutable"})
