from io import BytesIO
from types import SimpleNamespace
import httpx
import pytest
from PIL import Image
from app.services import chill
from app.models import Device, AssetPackage


def image(size=(800, 600), color="green"):
    out = BytesIO()
    Image.new("RGB", size, color).save(out, "JPEG")
    return out.getvalue()


@pytest.fixture(autouse=True)
def clean_chill():
    chill._recent.clear()
    chill._locks.clear()


@pytest.mark.parametrize("value", ["nature", "forest,ocean", "Bäume", "snow mountains"])
def test_keywords(value):
    assert chill.keyword(" " + value + " ") == value


@pytest.mark.parametrize("value", ["", "a" * 81, "../nature", "https://example.com", "a?random=4", "a,,b", "a\nb"])
def test_bad_keywords(value):
    with pytest.raises(ValueError): chill.keyword(value)


def test_conversion():
    raw = chill.convert(image())
    with Image.open(BytesIO(raw)) as photo:
        assert photo.size == (428, 142) and photo.mode == "RGB"
        assert not photo.info.get("progressive")
    with pytest.raises(ValueError): chill.convert(b"not a photo")
    assert len(raw) < 128 * 1024


@pytest.mark.parametrize("url", ["http://loremflickr.com/x", "https://localhost/a", "https://loremflickr.com.evil.org/a", "https://live.staticflickr.com:444/x", "https://user@loremflickr.com/a"])
def test_unsafe_redirect(url):
    assert not chill.safe_url(httpx.URL(url))


@pytest.mark.asyncio
async def test_real_download_protocol(monkeypatch):
    calls = []
    def respond(request):
        calls.append(request)
        if request.url.host == "loremflickr.com":
            assert request.url.path == "/428/142/forest,ocean"
            assert "random" in request.url.params
            return httpx.Response(302, headers={"location":"https://live.staticflickr.com/photo.jpg"})
        return httpx.Response(200, headers={"content-type":"image/jpeg"}, content=image())
    constructor = httpx.AsyncClient
    monkeypatch.setattr(chill.httpx, "AsyncClient", lambda **kw: constructor(transport=httpx.MockTransport(respond), **kw))
    assert await chill.download("forest,ocean")
    first = calls[0].url.params["random"]
    await chill.download("forest,ocean")
    assert calls[2].url.params["random"] != first


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["private_redirect", "html", "oversized", "timeout", "redirect_loop"])
async def test_download_failures(monkeypatch, kind):
    def respond(request):
        if kind == "timeout": raise httpx.ReadTimeout("timeout")
        if kind == "private_redirect": return httpx.Response(302, headers={"location":"https://127.0.0.1/private"})
        if kind == "redirect_loop": return httpx.Response(302, headers={"location":"/again"})
        if kind == "oversized": return httpx.Response(200, headers={"content-type":"image/jpeg","content-length":str(chill.MAX_DOWNLOAD + 1)})
        return httpx.Response(200, headers={"content-type":"text/html"}, content=b"<html>")
    constructor = httpx.AsyncClient
    monkeypatch.setattr(chill.httpx, "AsyncClient", lambda **kw: constructor(transport=httpx.MockTransport(respond), **kw))
    with pytest.raises((ValueError, httpx.HTTPError)): await chill.download("nature")


@pytest.mark.asyncio
async def test_bounded_cache_and_backoff(db, monkeypatch):
    calls = []
    async def download(topic):
        calls.append(topic)
        return image(color=(len(calls) * 30, 20, 80))
    monkeypatch.setattr(chill, "download", download)
    device = SimpleNamespace(id=1, device_id="leap-test", chill_keyword="nature")
    first = await chill.photo(device)
    assert await chill.photo(device) == first and len(calls) == 1
    for index in range(4):
        device.chill_keyword = f"nature{index}"
        await chill.photo(device)
    assert len(list(chill.photo_path(1, first["sha256"]).parent.glob("*.jpg"))) == 2
    async def fail(topic):
        calls.append(topic)
        raise ValueError("offline")
    monkeypatch.setattr(chill, "download", fail)
    device.chill_keyword = "offline"
    for _ in range(2):
        with pytest.raises(ValueError): await chill.photo(device)
    assert calls.count("offline") == 1
    assert len(list(chill.photo_path(1, first["sha256"]).parent.glob("*.jpg"))) == 2


def test_device_endpoints_and_form(client, db, monkeypatch):
    async def download(topic): return image()
    monkeypatch.setattr(chill, "download", download)
    device = Device(device_id="photo-test", name="Photos", content_selection=[chill.PACKAGE_ID])
    db.add(device); db.commit()
    assert client.get("/api/v1/devices/photo-test/config").json()["chill"]["keyword"] == "nature"
    response = client.get("/api/v1/devices/photo-test/chill/photo")
    assert response.status_code == 200
    info = response.json()
    assert (info["width"], info["height"]) == (428, 142)
    assert client.get(info["url"]).content == chill.photo_path(device.id, info["sha256"]).read_bytes()
    version = device.config_version
    response = client.post(f"/devices/{device.id}", data={"name":"Photos","age":8,"avatar":"dragon","enabled":"true","chill_keyword":"forest,ocean"})
    assert response.status_code == 200
    db.refresh(device)
    assert device.chill_keyword == "forest,ocean" and device.config_version > version
    assert 'value="forest,ocean"' in response.text
    assert client.get("/api/v1/devices/photo-test/config").json()["chill"]["keyword"] == "forest,ocean"
    assert client.post(f"/devices/{device.id}", data={"name":"Photos","age":8,"avatar":"dragon","chill_keyword":"../x"}).status_code == 422
    device.content_selection=[]; db.commit()
    assert client.get(info["url"]).status_code == 403
    assert client.get("/api/v1/devices/photo-test/chill/photo").status_code == 403
    device.enabled=False; db.commit()
    assert client.get("/api/v1/devices/photo-test/chill/photo").status_code == 404


def test_loremflickr_selection_sync_and_preview(client, db):
    from app.services import distribution
    from tests.test_distribution import device, sync
    d = device(db)
    response = client.post(f"/devices/{d.id}", data={"name":"Photos","age":8,"avatar":"dragon","enabled":"true","distribution_settings":"true","chill_id":chill.PACKAGE_ID,"chill_keyword":"ocean"}, follow_redirects=False)
    assert response.status_code == 303
    current = sync(client, firmware="1.1.0")
    assert chill.PACKAGE_ID in current["desiredAssets"]
    assert any(u["packageId"] == chill.PACKAGE_ID for u in current["assetUpdates"])
    old = sync(client, firmware="1.0.11")
    assert not any(u["packageId"] == chill.PACKAGE_ID for u in old["assetUpdates"])
    page = client.get(f"/devices/{d.id}").text
    assert 'data-scene="loremflickr"' in page and 'data-chill-photo-preview' in page
    assert 'name="chill_keyword" value="ocean"' in page
    package = db.get(AssetPackage, chill.PACKAGE_ID)
    assert distribution.current(db, package).manifest["definition"]["slider"] == {"min":0,"max":300,"default":200}
