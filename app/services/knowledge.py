import asyncio
import hashlib
import json
import re
from io import BytesIO
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup
from PIL import Image

from app.core.config import settings
from app.core.security import validate_external_url

SOURCES = {
    "klexikon": {"name": "Klexikon", "site": "https://klexikon.zum.de", "api": lambda: settings.klexikon_api_url},
    "miniklexikon": {"name": "MiniKlexikon", "site": "https://miniklexikon.zum.de", "api": lambda: settings.miniklexikon_api_url},
}
USER_AGENT = "LEAP-HomeServer/1.0 (kindgerechter Wiki-Browser)"


class KnowledgeNotFound(Exception): pass
class KnowledgeUnavailable(Exception): pass


def _key(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()


def _cache_path(kind: str, key: str) -> Path:
    path = settings.data_dir / "cache" / "knowledge" / kind
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{key}.json"


def _read_cache(kind: str, key: str, lifetime: timedelta) -> dict | None:
    path = _cache_path(kind, key)
    try:
        if datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) > lifetime:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _write_cache(kind: str, key: str, data: dict) -> None:
    path = _cache_path(kind, key)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _source(source: str) -> dict:
    if source not in SOURCES:
        raise ValueError("Unbekannte Wissensquelle")
    return SOURCES[source]


def _title(value: str) -> str:
    value = unescape(value).replace("_", " ").strip()
    if not value or len(value) > 180 or any(ord(character) < 32 for character in value):
        raise ValueError("Ungültiger Artikelname")
    return value


def _plain_text(page: dict) -> str:
    text = page.get("extract") or ""
    if "<" in text:
        soup = BeautifulSoup(text, "html.parser")
        text = "\n\n".join(element.get_text(" ", strip=True) for element in soup.select("p") if element.get_text(strip=True))
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _image_url(source: str, image_id: str | None) -> str | None:
    return f"/api/knowledge/image/{source}/{image_id}.jpg" if image_id else None


async def _cache_image(source: str, url: str | None, client: httpx.AsyncClient) -> str | None:
    if not url:
        return None
    image_id = _key(source, url)[:32]
    folder = settings.data_dir / "images" / "knowledge" / source
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{image_id}.jpg"
    if target.is_file():
        return image_id
    try:
        validate_external_url(url)
        response = await client.get(url)
        response.raise_for_status()
        if len(response.content) > settings.max_download_bytes:
            return None
        await asyncio.to_thread(_save_image, response.content, target)
        return image_id
    except Exception:
        return None


def _save_image(data: bytes, target: Path) -> None:
    with Image.open(BytesIO(data)) as image:
        output = image.convert("RGB")
        output.thumbnail((320, 180), Image.Resampling.LANCZOS)
        output.save(target, "JPEG", quality=82, optimize=True)


async def _request(source: str, params: dict, client: httpx.AsyncClient) -> dict:
    try:
        response = await client.get(_source(source)["api"](), params={"format": "json", "formatversion": 2, **params})
        response.raise_for_status()
        data = response.json()
        if data.get("error"):
            raise KnowledgeUnavailable("Wissensquelle hat die Anfrage abgelehnt")
        return data
    except (httpx.HTTPError, ValueError, json.JSONDecodeError) as error:
        raise KnowledgeUnavailable("Wissensquelle derzeit nicht erreichbar") from error


def _article_from_page(source: str, page: dict, image_id: str | None) -> dict:
    title = page["title"]
    links = []
    for link in page.get("links", [])[:12]:
        linked_title = link.get("title", "").strip()
        if linked_title and linked_title != title:
            links.append({"title": linked_title, "ref": quote(linked_title, safe="")})
    site = _source(source)["site"]
    return {"title": title, "articleRef": quote(title, safe=""), "source": source, "sourceName": _source(source)["name"], "originalTitle": title, "originalUrl": f"{site}/wiki/{quote(title.replace(' ', '_'))}", "license": "Lizenz und Urheberhinweise siehe Originalartikel", "text": _plain_text(page), "image": _image_url(source, image_id), "links": links}


async def article(source: str, title: str) -> dict:
    title = _title(title); cache_key = _key(source, title.casefold())
    lifetime = timedelta(hours=settings.knowledge_cache_hours)
    if cached := _read_cache("articles", cache_key, lifetime):
        return cached
    async with httpx.AsyncClient(timeout=settings.request_timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=False) as client:
        data = await _request(source, {"action": "query", "titles": title, "redirects": 1, "prop": "extracts|pageimages|links", "explaintext": 1, "exsectionformat": "plain", "piprop": "thumbnail", "pithumbsize": 640, "plnamespace": 0, "pllimit": 12}, client)
        pages = data.get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing"):
            raise KnowledgeNotFound("Wissensartikel nicht gefunden")
        page = pages[0]
        image_id = await _cache_image(source, page.get("thumbnail", {}).get("source"), client)
    result = _article_from_page(source, page, image_id)
    _write_cache("articles", cache_key, result)
    return result


async def search(source: str, query: str, limit: int = 8) -> dict:
    query = query.strip()
    if len(query) < 2 or len(query) > 80:
        raise ValueError("Suchbegriff muss zwischen 2 und 80 Zeichen lang sein")
    cache_key = _key(source, query.casefold(), str(limit))
    lifetime = timedelta(minutes=settings.knowledge_search_cache_minutes)
    if cached := _read_cache("search", cache_key, lifetime):
        return cached
    async with httpx.AsyncClient(timeout=settings.request_timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=False) as client:
        data = await _request(source, {"action": "query", "generator": "search", "gsrsearch": query, "gsrnamespace": 0, "gsrlimit": limit, "prop": "extracts|pageimages", "exintro": 1, "explaintext": 1, "exsentences": 2, "piprop": "thumbnail", "pithumbsize": 320}, client)
        pages = sorted(data.get("query", {}).get("pages", []), key=lambda page: page.get("index", 999))
        image_ids = await asyncio.gather(*(_cache_image(source, page.get("thumbnail", {}).get("source"), client) for page in pages))
    result = {"source": source, "results": [{"title": page["title"], "articleRef": quote(page["title"], safe=""), "description": _plain_text(page), "image": _image_url(source, image_id)} for page, image_id in zip(pages, image_ids)]}
    _write_cache("search", cache_key, result)
    return result


async def random_article(source: str) -> dict:
    async with httpx.AsyncClient(timeout=settings.request_timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=False) as client:
        data = await _request(source, {"action": "query", "list": "random", "rnnamespace": 0, "rnlimit": 1}, client)
    rows = data.get("query", {}).get("random", [])
    if not rows:
        raise KnowledgeUnavailable("Zufälliger Wissensartikel konnte nicht geladen werden")
    return await article(source, rows[0]["title"])


def demo_article(source: str) -> dict:
    return {"title": "Saturn", "sourceName": _source(source)["name"], "text": "Der Saturn ist ein Planet in unserem Sonnensystem. Besonders auffällig sind seine Ringe aus Eis und Gestein.", "image": "/static/knowledge-saturn.svg", "links": [{"title": "Sonnensystem"}, {"title": "Planet"}, {"title": "Jupiter"}]}
