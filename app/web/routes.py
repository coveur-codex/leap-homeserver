import json
from datetime import datetime
from fastapi import APIRouter,Depends,File,Form,HTTPException,Request,UploadFile
from fastapi.responses import HTMLResponse,RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func,select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.pages import PAGE_REGISTRY
from app.models import Article,Category,Device,Feed,QuizCatalog,QuizQuestion
from app.services.devices import initialize_pages
from app.services.feeds import fetch_feed
from app.services.news import articles_for_device
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
    return templates.TemplateResponse(request,"device_edit.html",{"device":d,"registry":PAGE_REGISTRY,"categories":db.scalars(select(Category)).all(),"feeds":db.scalars(select(Feed)).all(),"catalogs":db.scalars(select(QuizCatalog)).all(),"preview_articles":articles_for_device(d,db,limit=min(d.news_limit,8)),"preview_now":datetime.now()})
@router.post("/devices/{id}")
def update_device(id:int,name:str=Form(),child_name:str=Form(""),age:int=Form(),avatar:str=Form(),avatar_name:str=Form(""),enabled:bool=Form(False),category_ids:list[int]=Form([]),page_ids:list[str]=Form([]),page_positions:list[int]=Form([]),weather_location:str=Form(""),latitude:str=Form(""),longitude:str=Form(""),news_limit:int=Form(20),news_max_age_hours:int=Form(48),db:Session=Depends(get_db)):
    d=db.get(Device,id)
    if not d: raise HTTPException(404)
    d.name=name; d.child_name=child_name; d.age=age; d.avatar=avatar; d.avatar_name=avatar_name; d.enabled=enabled; d.categories=[c for x in category_ids if (c:=db.get(Category,x))]; d.weather_location=weather_location; d.latitude=float(latitude) if latitude else None; d.longitude=float(longitude) if longitude else None; d.news_limit=news_limit; d.news_max_age_hours=news_max_age_hours
    positions=dict(zip((page.page_id for page in d.pages),page_positions))
    for pos,pid in enumerate(page_ids,1):
        if page:=next((x for x in d.pages if x.page_id==pid),None): page.enabled=True; page.position=positions.get(pid,pos)
    for page in d.pages:
        if page.page_id not in page_ids: page.enabled=False
    d.config_version+=1; db.commit(); return redir(f"/devices/{id}")
@router.post("/devices/{id}/delete")
def delete_device(id:int,db:Session=Depends(get_db)): db.delete(db.get(Device,id)); db.commit(); return redir("/devices")
@router.post("/devices/{id}/duplicate")
def duplicate_device(id:int,db:Session=Depends(get_db)):
    old=db.get(Device,id); d=Device(device_id=old.device_id+"-copy",name=old.name+" (Kopie)",child_name=old.child_name,age=old.age,avatar=old.avatar,avatar_name=old.avatar_name); initialize_pages(d); db.add(d); db.commit(); return redir(f"/devices/{d.id}")
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
@router.get("/quiz",response_class=HTMLResponse)
def quiz(request:Request,db:Session=Depends(get_db)): return templates.TemplateResponse(request,"quiz.html",{"catalogs":db.scalars(select(QuizCatalog)).all(),"devices":db.scalars(select(Device)).all()})
@router.post("/quiz/upload")
async def upload_quiz(name:str=Form(),file:UploadFile=File(),device_ids:list[int]=Form([]),db:Session=Depends(get_db)):
    if not file.filename or not file.filename.lower().endswith(".json"): raise HTTPException(400,"Nur JSON-Dateien")
    raw=await file.read(2_000_001)
    if len(raw)>2_000_000: raise HTTPException(413,"Datei zu groß")
    try: data=json.loads(raw)
    except Exception: raise HTTPException(400,"Ungültiges JSON")
    cat=QuizCatalog(name=name); db.add(cat)
    for q in data if isinstance(data,list) else data.get("questions",[]):
        if isinstance(q.get("q"),str) and isinstance(q.get("a"),list) and len(q["a"])==4: cat.questions.append(QuizQuestion(question=q["q"],answers=q["a"],explanation=q.get("explanation",""),min_age=int(q.get("minAge",0)),difficulty=int(q.get("difficulty",1)),tags=q.get("tags",[])))
    for id in device_ids:
        if d:=db.get(Device,id): d.quiz_catalogs.append(cat); d.quiz_version+=1
    db.commit(); return redir("/quiz")
@router.get("/system",response_class=HTMLResponse)
def system(request:Request,db:Session=Depends(get_db)):
    from app import __version__; from app.core.config import settings
    size=lambda p:sum(x.stat().st_size for x in p.rglob("*") if x.is_file())
    return templates.TemplateResponse(request,"system.html",{"version":__version__,"database":settings.database_url,"cache_size":size(settings.data_dir/"cache"),"image_size":size(settings.data_dir/"images"),"feeds":db.scalar(select(func.count(Feed.id))),"errors":db.scalar(select(func.count(Feed.id)).where(Feed.last_error.is_not(None)))})
