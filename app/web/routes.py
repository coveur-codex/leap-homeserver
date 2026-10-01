import re
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter,Depends,File,Form,HTTPException,Request,UploadFile
from fastapi.responses import HTMLResponse,RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func,select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.pages import PAGE_REGISTRY
from app.models import Article,Category,Device,Feed,LocationCache,QuizCatalog,QuizQuestion
from app.services.devices import initialize_pages
from app.services.feeds import fetch_feed
from app.services.news import articles_for_device
from app.services.location_data import cache_for_device
from app.services.knowledge import demo_article
from app.services import distribution as distribution_service
from app.models import AssetPackage
router=APIRouter(); templates=Jinja2Templates(directory="app/templates")
def redir(p): return RedirectResponse(p,303)
@router.get("/",response_class=HTMLResponse)
def dashboard(request:Request,db:Session=Depends(get_db)): return templates.TemplateResponse(request,"dashboard.html",{"devices":db.scalars(select(Device)).all(),"device_count":db.scalar(select(func.count(Device.id))),"feed_count":db.scalar(select(func.count(Feed.id)).where(Feed.enabled==True)),"article_count":db.scalar(select(func.count(Article.id))),"feed_errors":db.scalar(select(func.count(Feed.id)).where(Feed.last_error.is_not(None)))})
@router.get("/devices",response_class=HTMLResponse)
def devices(request:Request,db:Session=Depends(get_db)): return templates.TemplateResponse(request,"devices.html",{"devices":db.scalars(select(Device).order_by(Device.name)).all()})
@router.post("/devices")
def create_device(device_id:str=Form(),name:str=Form(),child_name:str=Form(""),age:int=Form(8),avatar:str=Form("dragon"),avatar_name:str=Form(""),db:Session=Depends(get_db)):
    if db.scalar(select(Device).where(Device.device_id==device_id)): raise HTTPException(409,"device_id bereits vorhanden")
    d=Device(device_id=device_id,name=name,child_name=child_name,age=age,avatar=avatar,avatar_name=avatar_name); initialize_pages(d); db.add(d); db.commit(); return redir(f"/devices/{d.id}")
@router.get("/devices/{id}",response_class=HTMLResponse)
def edit_device(id:int,request:Request,db:Session=Depends(get_db)):
    d=db.get(Device,id)
    if not d: raise HTTPException(404)
    distribution_service.ensure_packages(db)
    location_cache=cache_for_device(d,db)
    enabled_page_ids=[page.page_id for page in sorted(d.pages,key=lambda page:page.position) if page.enabled]
    preview_page_ids=[page_id for page_id in enabled_page_ids if page_id in {"home","news","weather","quiz","aircraft","knowledge"}]
    catalog_ids=[catalog.id for catalog in d.quiz_catalogs if catalog.enabled]
    preview_question=db.scalar(select(QuizQuestion).where(QuizQuestion.catalog_id.in_(catalog_ids),QuizQuestion.min_age<=d.age).order_by(QuizQuestion.id)) if catalog_ids else None
    return templates.TemplateResponse(request,"device_edit.html",{"device":d,"registry":PAGE_REGISTRY,"categories":db.scalars(select(Category)).all(),"feeds":db.scalars(select(Feed)).all(),"catalogs":db.scalars(select(QuizCatalog)).all(),"preview_page_ids":preview_page_ids,"preview_articles":articles_for_device(d,db,limit=min(d.news_limit,8)),"preview_weather":location_cache.weather_data if location_cache else None,"preview_aircraft":location_cache.aircraft_data if location_cache else None,"preview_question":preview_question,"preview_knowledge":demo_article(d.knowledge_source),"preview_now":datetime.now(),**distribution_service.device_context(db,d)})
@router.post("/devices/{id}")
def update_device(id:int,name:str=Form(),child_name:str=Form(""),age:int=Form(),avatar:str=Form(),device_id:str|None=Form(None),avatar_name:str=Form(""),enabled:bool=Form(False),category_ids:list[int]=Form([]),page_ids:list[str]=Form([]),page_positions:list[int]=Form([]),knowledge_source:str=Form("klexikon"),weather_location:str=Form(""),latitude:str=Form(""),longitude:str=Form(""),news_limit:int=Form(20),news_max_age_hours:int=Form(48),firmware_channel:str=Form("stable"),content_ids:list[str]=Form([]),quiz_catalog_ids:list[int]=Form([]),distribution_settings:bool=Form(False),db:Session=Depends(get_db)):
    d=db.get(Device,id)
    if not d: raise HTTPException(404)
    new_device_id=(device_id or d.device_id).strip()
    if len(new_device_id)>80 or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*",new_device_id): raise HTTPException(422,"Device-ID darf höchstens 80 Zeichen sowie nur Kleinbuchstaben, Zahlen und einzelne Bindestriche enthalten")
    if db.scalar(select(Device).where(Device.device_id==new_device_id,Device.id!=id)): raise HTTPException(409,"Device-ID bereits vorhanden")
    if knowledge_source not in {"klexikon","miniklexikon"}: raise HTTPException(422,"Unbekannte Wissensquelle")
    if distribution_settings:
        distribution_service.ensure_packages(db)
        if firmware_channel not in {"stable", "beta"}: raise HTTPException(422,"Ungültiger Firmware-Kanal")
        if any(not (p:=db.get(AssetPackage,key)) or p.kind not in {"chill","sound","weather","game"} for key in content_ids): raise HTTPException(422,"Unbekannte Inhaltsauswahl")
        if any(not db.get(QuizCatalog,key) for key in quiz_catalog_ids): raise HTTPException(422,"Unbekannter Quiz-Katalog")
        avatar_id=avatar if avatar.startswith("avatar-") else "avatar-"+avatar
        avatar_package=db.get(AssetPackage,avatar_id)
        if not avatar_package or avatar_package.kind!="avatar": raise HTTPException(422,"Unbekannter Avatar")
        if avatar.removeprefix("avatar-") in distribution_service.BUILTINS:
            avatar=avatar.removeprefix("avatar-")
        d.firmware_channel=firmware_channel
        d.content_selection=sorted(set(content_ids))
        d.quiz_catalogs=[db.get(QuizCatalog,key) for key in set(quiz_catalog_ids)]
        d.quiz_version+=1
    old_knowledge_source=d.knowledge_source
    d.device_id=new_device_id; d.name=name; d.child_name=child_name; d.age=age; d.avatar=avatar; d.avatar_name=avatar_name; d.enabled=enabled; d.categories=[c for x in category_ids if (c:=db.get(Category,x))]; d.weather_location=weather_location; d.latitude=float(latitude) if latitude else None; d.longitude=float(longitude) if longitude else None; d.news_limit=news_limit; d.news_max_age_hours=news_max_age_hours; d.knowledge_source=knowledge_source
    positions=dict(zip((page.page_id for page in d.pages),page_positions))
    for pos,pid in enumerate(page_ids,1):
        if page:=next((x for x in d.pages if x.page_id==pid),None): page.enabled=True; page.position=positions.get(pid,pos)
    for page in d.pages:
        if page.page_id not in page_ids: page.enabled=False
    if old_knowledge_source != knowledge_source: d.knowledge_version+=1
    d.config_version+=1; db.commit(); return redir(f"/devices/{id}")
@router.post("/devices/{id}/delete")
def delete_device(id:int,db:Session=Depends(get_db)): db.delete(db.get(Device,id)); db.commit(); return redir("/devices")
@router.post("/devices/{id}/duplicate")
def duplicate_device(id:int,db:Session=Depends(get_db)):
    old=db.get(Device,id); d=Device(device_id=old.device_id+"-copy",name=old.name+" (Kopie)",child_name=old.child_name,age=old.age,avatar=old.avatar,avatar_name=old.avatar_name,weather_location=old.weather_location,latitude=old.latitude,longitude=old.longitude,temperature_unit=old.temperature_unit,knowledge_source=old.knowledge_source,firmware_channel=old.firmware_channel,content_selection=list(old.content_selection),quiz_catalogs=list(old.quiz_catalogs)); initialize_pages(d); db.add(d); db.commit(); return redir(f"/devices/{d.id}")
@router.get("/news/feeds",response_class=HTMLResponse)
def feeds(request:Request,db:Session=Depends(get_db)): return templates.TemplateResponse(request,"feeds.html",{"feeds":db.scalars(select(Feed)).all(),"categories":db.scalars(select(Category)).all(),"articles":db.scalars(select(Article).order_by(Article.published_at.desc()).limit(20)).all()})
@router.post("/news/categories")
def category(slug:str=Form(),name:str=Form(),db:Session=Depends(get_db)): db.add(Category(slug=slug.lower().strip(),name=name)); db.commit(); return redir("/news/feeds")
@router.post("/news/feeds")
async def add_feed(name:str=Form(),url:str=Form(),category_id:int|None=Form(None),update_interval:int=Form(15),image_mode:str=Form("center_crop"),db:Session=Depends(get_db)):
    feed=Feed(name=name,url=url,category_id=category_id,update_interval=update_interval,image_mode=image_mode); db.add(feed); db.commit(); await fetch_feed(feed,db); return redir("/news/feeds")
@router.post("/news/feeds/{id}/fetch")
async def refresh_feed(id:int,db:Session=Depends(get_db)): await fetch_feed(db.get(Feed,id),db); return redir("/news/feeds")
@router.post("/news/feeds/{id}/delete")
def delete_feed(id:int,db:Session=Depends(get_db)): db.delete(db.get(Feed,id)); db.commit(); return redir("/news/feeds")
@router.get("/quiz")
def quiz(): return redir("/assets?kind=quiz")
@router.post("/quiz/upload")
async def upload_quiz(name:str=Form(),file:UploadFile=File(),device_ids:list[int]=Form([]),db:Session=Depends(get_db)):
    if not file.filename or not file.filename.lower().endswith(".json"): raise HTTPException(400,"Nur JSON-Dateien")
    raw=await file.read(2_000_001)
    if len(raw)>2_000_000: raise HTTPException(413,"Datei zu groß")
    rows=distribution_service.parse_questions(raw)
    cat=QuizCatalog(name=name); db.add(cat)
    cat.questions=[QuizQuestion(question=q["q"],answers=q["a"],explanation=q["explanation"],min_age=q["minAge"],difficulty=q["difficulty"],tags=q["tags"]) for q in rows]
    for id in device_ids:
        if d:=db.get(Device,id): d.quiz_catalogs.append(cat); d.quiz_version+=1
    db.flush()
    package=AssetPackage(id=distribution_service.catalog_package_id(db,cat),kind="quiz",name=name,catalog_id=cat.id,current_version=0)
    db.add(package); db.flush()
    distribution_service.publish_quiz(db,package,cat,0)
    db.commit(); return redir(f"/assets/{package.id}")
@router.get("/system",response_class=HTMLResponse)
def system(request:Request,db:Session=Depends(get_db)):
    from app import __version__; from app.core.config import settings
    size=lambda p:sum(x.stat().st_size for x in p.rglob("*") if x.is_file())
    now=datetime.now(timezone.utc)
    started_at=getattr(request.app.state,"started_at",now)
    locations=db.scalars(select(LocationCache).order_by(LocationCache.location,LocationCache.location_key)).all()
    def aware(value):
        return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value
    location_status=[]
    for location in locations:
        weather_at=aware(location.weather_fetched_at); aircraft_at=aware(location.aircraft_fetched_at)
        location_status.append({"name":location.location or location.location_key,"coordinates":f"{location.latitude:.5f}, {location.longitude:.5f}","weather_at":weather_at,"weather_next":weather_at+timedelta(minutes=settings.weather_cache_minutes) if weather_at else None,"weather_error":location.weather_error,"aircraft_at":aircraft_at,"aircraft_next":aircraft_at+timedelta(minutes=settings.weather_cache_minutes) if aircraft_at else None,"aircraft_error":location.aircraft_error})
    latest_feed=db.scalar(select(func.max(Feed.last_success)))
    return templates.TemplateResponse(request,"system.html",{"version":__version__,"database":make_url(settings.database_url).render_as_string(hide_password=True),"cache_size":size(settings.data_dir/"cache"),"image_size":size(settings.data_dir/"images"),"feeds":db.scalar(select(func.count(Feed.id))),"errors":db.scalar(select(func.count(Feed.id)).where(Feed.last_error.is_not(None))),"articles":db.scalar(select(func.count(Article.id))),"devices":db.scalar(select(func.count(Device.id))),"active_devices":db.scalar(select(func.count(Device.id)).where(Device.enabled.is_(True))),"latest_feed":aware(latest_feed),"locations":location_status,"location_interval":settings.weather_cache_minutes,"aircraft_radius":settings.aircraft_radius_nm,"started_at":started_at,"uptime":now-started_at,"now":now})
