import hashlib, html, re, unicodedata
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin
import feedparser, httpx
from bs4 import BeautifulSoup
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.layout import SUMMARY_MAX_CHARS
from app.core.security import validate_external_url
from app.models import Article, Device, Feed
from .images import download_and_process

def clean_text(value: str|None) -> str:
    text = BeautifulSoup(html.unescape(value or ""), "html.parser").get_text(" ")
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()
def summarize_article(value: str, limit: int=SUMMARY_MAX_CHARS) -> str:
    clean=clean_text(value)
    if len(clean)<=limit: return clean
    cut=clean[:limit+1].rsplit(" ",1)[0]
    return cut.rstrip(".,;:")+"…"
def article_hash(title: str, published: datetime) -> str:
    return hashlib.sha256(f"{clean_text(title).casefold()}|{published.date().isoformat()}".encode()).hexdigest()
def find_image(entry) -> str|None:
    for key in ("media_content","media_thumbnail"):
        for item in entry.get(key,[]):
            if item.get("url"): return item["url"]
    for item in entry.get("enclosures",[]):
        if item.get("href") and (item.get("type","").startswith("image/") or not item.get("type")): return item["href"]
    soup=BeautifulSoup(entry.get("content",[{}])[0].get("value","") if entry.get("content") else entry.get("summary",""), "html.parser")
    img=soup.find("img")
    return img.get("src") if img else None
def parse_date(entry) -> datetime:
    for key in ("published_parsed","updated_parsed"):
        if entry.get(key): return datetime(*entry[key][:6], tzinfo=timezone.utc)
    for key in ("published","updated"):
        try: return parsedate_to_datetime(entry.get(key)).astimezone(timezone.utc)
        except Exception: pass
    return datetime.now(timezone.utc)
def parse_feed(content: bytes, feed: Feed, db: Session) -> tuple[int,int]:
    parsed=feedparser.parse(content); created=images=0
    for entry in parsed.entries:
        title=clean_text(entry.get("title")); url=entry.get("link",""); published=parse_date(entry)
        if not title or not url: continue
        digest=article_hash(title,published); guid=str(entry.get("id") or entry.get("guid") or "")
        exists=db.scalar(select(Article).where(or_(Article.hash==digest, Article.url==url, Article.external_id==guid if guid else Article.hash==digest)))
        if exists: continue
        raw=entry.get("summary") or (entry.get("content",[{}])[0].get("value","") if entry.get("content") else "")
        article=Article(external_id=guid or None,feed_id=feed.id,category=feed.category.slug if feed.category else "allgemein",title=title,summary=summarize_article(raw),content=clean_text(raw),source=feed.name,url=url,published_at=published,hash=digest)
        db.add(article); db.flush(); image=find_image(entry)
        if image and feed.image_mode!="disabled":
            try:
                original,leap=download_and_process(urljoin(url,image),article.id,feed.image_mode)
                article.image_original=original; article.image_leap=leap; images+=1
            except Exception: pass
        created+=1
    if created:
        category = feed.category.slug if feed.category else "allgemein"
        for device in db.scalars(select(Device)).all():
            interested = any(item.slug == category for item in device.categories)
            explicitly_included = feed.id in (device.included_feed_ids or [])
            if feed.id not in (device.excluded_feed_ids or []) and (interested or explicitly_included):
                device.news_version += 1
    db.commit(); return created,images
async def fetch_feed(feed: Feed, db: Session) -> dict:
    validate_external_url(feed.url); feed.last_fetch=datetime.now(timezone.utc)
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout, follow_redirects=False) as client:
            response=await client.get(feed.url,headers={"User-Agent":"LEAP-HomeServer/1.0"}); response.raise_for_status()
            if len(response.content)>settings.max_download_bytes: raise ValueError("Feed ist zu groß")
        created,images=parse_feed(response.content,feed,db); parsed=feedparser.parse(response.content)
        feed.last_success=datetime.now(timezone.utc); feed.last_error=None; db.commit()
        return {"ok":True,"format":parsed.version or "unbekannt","found":len(parsed.entries),"created":created,"images":images}
    except Exception as exc:
        feed.last_error=str(exc)[:1000]; db.commit(); return {"ok":False,"error":str(exc)}
