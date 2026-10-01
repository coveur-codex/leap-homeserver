from datetime import datetime, timezone
from pathlib import Path
import re
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models import Device, QuizQuestion
from app.services.news import articles_for_device
from app.services.location_data import data_for_device
from app.services import knowledge as knowledge_service
router=APIRouter(prefix="/api/v1")
leap_router=APIRouter(prefix="/api/leap")
knowledge_asset_router=APIRouter(prefix="/api/knowledge")
def device_or_404(device_id:str,db:Session)->Device:
    d=db.scalar(select(Device).where(Device.device_id==device_id,Device.enabled==True))
    if not d: raise HTTPException(404,"Gerät nicht gefunden")
    return d
class Checkin(BaseModel):
    firmwareVersion:str|None=None; battery:int|None=Field(None,ge=0,le=100); wifiRssi:int|None=None; freeFlash:int|None=None
@router.get("/devices/{device_id}/config")
def config(device_id:str,db:Session=Depends(get_db)):
    d=device_or_404(device_id,db)
    return {"deviceId":d.device_id,"configVersion":d.config_version,"name":d.name,"childName":d.child_name,"age":d.age,"avatar":d.avatar,"avatarName":d.avatar_name,"avatarConfig":d.avatar_config,"firmwareChannel":d.firmware_channel,"contentSelection":d.content_selection,"quizCatalogs":[c.id for c in d.quiz_catalogs if c.enabled],"knowledgeSource":d.knowledge_source,"pages":[{"id":p.page_id,"title":p.title,"enabled":p.enabled,"order":p.position,"settings":p.settings} for p in d.pages],"games":[{"id":x,"enabled":True} for x in ("hot_potato","simon_motion","tilt_maze")],"homeSlots":d.home_slots}
@router.get("/devices/{device_id}/version")
def version(device_id:str,db:Session=Depends(get_db)):
    d=device_or_404(device_id,db); return {"configVersion":d.config_version,"contentVersion":max(d.news_version,d.weather_version,d.aircraft_version,d.quiz_version,d.knowledge_version)}
@router.get("/devices/{device_id}/sync")
def sync(device_id:str,db:Session=Depends(get_db)):
    d=device_or_404(device_id,db); return {"configVersion":d.config_version,"newsVersion":d.news_version,"weatherVersion":d.weather_version,"aircraftVersion":d.aircraft_version,"quizVersion":d.quiz_version,"knowledgeVersion":d.knowledge_version}
@router.post("/devices/{device_id}/checkin")
def checkin(device_id:str,data:Checkin,db:Session=Depends(get_db)):
    d=device_or_404(device_id,db); d.last_seen=datetime.now(timezone.utc); d.firmware_version=data.firmwareVersion; d.battery=data.battery; d.wifi_rssi=data.wifiRssi; d.free_flash=data.freeFlash; db.commit(); return {"ok":True,"serverTime":d.last_seen}
@router.get("/devices/{device_id}/news")
def news(device_id:str,limit:int|None=Query(None,ge=1,le=100),since:datetime|None=None,db:Session=Depends(get_db)):
    d=device_or_404(device_id,db); rows=articles_for_device(d,db,limit=limit,since=since)
    return {"version":d.news_version,"articles":[{"id":f"news_{a.id}","category":a.category,"title":a.title,"summary":a.summary,"source":a.source,"published":a.published_at,"image":f"/api/v1/assets/news/{a.id}/thumb.jpg" if a.image_leap else None} for a in rows]}
@router.get("/devices/{device_id}/weather")
async def weather(device_id:str,db:Session=Depends(get_db)):
    d=device_or_404(device_id,db)
    try:return await data_for_device(d,db,"weather")
    except ValueError as e: raise HTTPException(422,str(e))
    except Exception as e: raise HTTPException(503,"Wetterdienst derzeit nicht verfügbar")
@router.get("/devices/{device_id}/aircraft")
async def aircraft(device_id:str,db:Session=Depends(get_db)):
    d=device_or_404(device_id,db)
    try:
        data=await data_for_device(d,db,"aircraft")
        return {"version":d.aircraft_version,**data}
    except ValueError as e: raise HTTPException(422,str(e))
    except Exception: raise HTTPException(503,"Flugradar derzeit nicht verfügbar")
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

def knowledge_device(device_id: str, db: Session) -> Device:
    device = device_or_404(device_id, db)
    page = next((page for page in device.pages if page.page_id == "knowledge"), None)
    if not page or not page.enabled:
        raise HTTPException(403, "Wissen ist für dieses Gerät nicht aktiviert")
    return device

def knowledge_error(error: Exception):
    if isinstance(error, ValueError): raise HTTPException(422, str(error))
    if isinstance(error, knowledge_service.KnowledgeNotFound): raise HTTPException(404, str(error))
    if isinstance(error, knowledge_service.KnowledgeUnavailable): raise HTTPException(503, str(error))
    raise error

@router.get("/devices/{device_id}/knowledge/article/{title}")
@leap_router.get("/{device_id}/knowledge/article/{title}")
async def knowledge_article(device_id:str,title:str,db:Session=Depends(get_db)):
    device=knowledge_device(device_id,db)
    try: return await knowledge_service.article(device.knowledge_source,title)
    except Exception as error: knowledge_error(error)

@router.get("/devices/{device_id}/knowledge/search")
@leap_router.get("/{device_id}/knowledge/search")
async def knowledge_search(device_id:str,q:str=Query(...,min_length=1,max_length=80),limit:int=Query(8,ge=1,le=12),db:Session=Depends(get_db)):
    device=knowledge_device(device_id,db)
    try: return await knowledge_service.search(device.knowledge_source,q,limit)
    except Exception as error: knowledge_error(error)

@router.get("/devices/{device_id}/knowledge/random")
@leap_router.get("/{device_id}/knowledge/random")
async def knowledge_random(device_id:str,db:Session=Depends(get_db)):
    device=knowledge_device(device_id,db)
    try: return await knowledge_service.random_article(device.knowledge_source)
    except Exception as error: knowledge_error(error)

@router.get("/assets/knowledge/{source}/{image_id}.jpg")
@knowledge_asset_router.get("/image/{source}/{image_id}.jpg")
def knowledge_image(source:str,image_id:str):
    if source not in knowledge_service.SOURCES or not re.fullmatch(r"[a-f0-9]{32}",image_id): raise HTTPException(404)
    from app.core.config import settings
    path=settings.data_dir/"images"/"knowledge"/source/f"{image_id}.jpg"
    if not path.is_file(): raise HTTPException(404,"Wissensbild nicht gefunden")
    return FileResponse(path,media_type="image/jpeg",headers={"Cache-Control":"public, max-age=604800, immutable"})
