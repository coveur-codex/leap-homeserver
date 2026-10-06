import logging, time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from app import __version__
from app.api.routes import knowledge_asset_router, leap_router, router as api_router
from app.core.config import settings
from app.core.database import SessionLocal
from app.models import Article,Category,Device,Feed
from app.services.devices import initialize_pages
from app.services.feeds import fetch_feed
from app.services.location_data import refresh_configured_locations
from app.web.routes import router as web_router
from app.api.distribution import router as distribution_api
from app.web.distribution import router as distribution_web
logging.basicConfig(level=settings.log_level,format='%(asctime)s %(levelname)s %(name)s %(message)s')
log=logging.getLogger("leap"); START=time.monotonic()
async def scheduled_feeds():
    with SessionLocal() as db:
        now=datetime.now(timezone.utc)
        for feed in db.scalars(select(Feed).where(Feed.enabled==True)).all():
            last=feed.last_fetch.replace(tzinfo=timezone.utc) if feed.last_fetch and feed.last_fetch.tzinfo is None else feed.last_fetch
            if not last or last < now-timedelta(minutes=feed.update_interval): await fetch_feed(feed,db)
def cleanup():
    with SessionLocal() as db:
        old=db.scalars(select(Article).where(Article.fetched_at<datetime.now(timezone.utc)-timedelta(days=settings.news_retention_days))).all()
        for a in old: db.delete(a)
        db.commit()
async def scheduled_location_data():
    with SessionLocal() as db:
        count=await refresh_configured_locations(db)
        log.info("location_refresh locations=%s",count)
def seed():
    if not settings.seed_demo_data:return
    with SessionLocal() as db:
        for slug,name in [("technik","Technik"),("gaming","Gaming"),("weltraum","Weltraum"),("tiere","Tiere"),("natur","Natur"),("sport","Sport")]:
            if not db.scalar(select(Category).where(Category.slug==slug)):db.add(Category(slug=slug,name=name))
        db.flush()
        for did,name,avatar,age in [("leap-erik","Erik","dragon",9),("leap-anna","Anna","jellyfish",8),("leap-lars","Lars","walrus",10)]:
            if not db.scalar(select(Device).where(Device.device_id==did)):
                d=Device(device_id=did,name=name,child_name=name,avatar=avatar,age=age);initialize_pages(d);db.add(d)
        db.commit()
@asynccontextmanager
async def lifespan(app):
    app.state.started_at=datetime.now(timezone.utc)
    from app.services.distribution import ensure_packages
    with SessionLocal() as db:
        ensure_packages(db)
    scheduler=AsyncIOScheduler()
    log.info("server_start version=%s",__version__); seed(); scheduler.add_job(scheduled_feeds,"interval",minutes=1,max_instances=1,coalesce=True,id="feeds");scheduler.add_job(scheduled_location_data,"interval",seconds=settings.aircraft_cache_seconds,max_instances=1,coalesce=True,id="location-data");scheduler.add_job(cleanup,"cron",hour=3,id="cleanup");scheduler.start();yield;scheduler.shutdown(wait=False)
app=FastAPI(title="LEAP Home Server",version=__version__,lifespan=lifespan)
app.mount("/static",StaticFiles(directory="app/static"),name="static");app.include_router(api_router);app.include_router(leap_router);app.include_router(knowledge_asset_router);app.include_router(web_router)

app.include_router(distribution_api)
app.include_router(distribution_web)
from app.web.communication import router as communication_web
app.include_router(communication_web)
