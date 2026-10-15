from io import BytesIO
from types import SimpleNamespace
import httpx
import pytest
from PIL import Image
from app.services import chill
from app.models import Device, AssetPackage
from app.services.chill import download_picsum as real_download_picsum


def image(size=(800, 600), color="green"):
    out = BytesIO()
    Image.new("RGB", size, color).save(out, "JPEG")
    return out.getvalue()


@pytest.fixture(autouse=True)
def clean_chill(monkeypatch):
    chill._recent.clear()
    chill._locks.clear()
    chill._fetches.clear()
    chill._primary_retry_at = 0
    async def unavailable(): raise ValueError("Picsum unavailable in this test")
    monkeypatch.setattr(chill, "download_picsum", unavailable)



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
    def client_with_read_budget(**kw):
        assert kw["timeout"].read == 60 and kw["timeout"].connect == 5
        return constructor(transport=httpx.MockTransport(respond), **kw)
    monkeypatch.setattr(chill.httpx, "AsyncClient", client_with_read_budget)
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


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,stage,reason", [
    ("status", "download", "HTTP 429 from loremflickr.com"),
    ("connection", "download", "Name or service not known"),
    ("timeout", "download", "TimeoutError"),
    ("decode", "decode", "Ungültige Bilddaten"),
    ("disk", "cache", "Permission denied"),
])
async def test_photo_failure_diagnostics(db, monkeypatch, caplog, failure, stage, reason):
    device = SimpleNamespace(id=1, device_id="leap-papa", chill_keyword="nature")
    async def download(topic):
        if failure == "status":
            response = httpx.Response(429, request=httpx.Request("GET", "https://loremflickr.com/428/142/nature?random=1"))
            response.raise_for_status()
        if failure == "connection": raise httpx.ConnectError("Name or service not known")
        if failure == "timeout": raise TimeoutError()
        return b"invalid" if failure == "decode" else image()
    monkeypatch.setattr(chill, "download", download)
    if failure == "disk":
        from pathlib import Path
        def deny(*args, **kwargs): raise PermissionError("Permission denied")
        monkeypatch.setattr(Path, "mkdir", deny)
    with pytest.raises((ValueError, TimeoutError, OSError, httpx.HTTPError)):
        await chill.photo(device)
    failures = [record for record in caplog.records if record.message.startswith("chill_photo_failed")]
    assert len(failures) == 1
    assert f"device=leap-papa stage={stage}" in failures[0].message
    assert reason in failures[0].message
    # A cached failure must not flood logs or perform another external request.
    with pytest.raises(ValueError, match="erneuten Versuch"):
        await chill.photo(device)
    assert len([r for r in caplog.records if r.message.startswith("chill_photo_failed")]) == 1


@pytest.mark.asyncio
async def test_rejected_image_logs_redirect_host_and_content_type(db, monkeypatch, caplog):
    constructor = httpx.AsyncClient
    responses = [httpx.Response(302, headers={"location": "https://unexpected.example/photo.jpg"}),
                 httpx.Response(200, headers={"content-type": "text/html"}, content=b"html")]
    for index, response in enumerate(responses):
        chill._primary_retry_at = 0
        monkeypatch.setattr(chill.httpx, "AsyncClient", lambda **kw: constructor(transport=httpx.MockTransport(lambda req: response), **kw))
        with pytest.raises(ValueError):
            await chill.photo(SimpleNamespace(id=index, device_id="leap-papa", chill_keyword="nature"))
    assert "unexpected.example" in caplog.text and "text/html" in caplog.text


@pytest.mark.asyncio
async def test_slow_photo_survives_retries_and_is_delivered_once_ready(db, monkeypatch):
    import asyncio
    release = asyncio.Event()
    calls = []
    async def slow_download(topic):
        calls.append(topic)
        await release.wait()
        return image()
    monkeypatch.setattr(chill, "download", slow_download)
    monkeypatch.setattr(chill, "PHOTO_RESPONSE_WAIT", .01)
    d = SimpleNamespace(id=1, device_id="leap-papa", chill_keyword="nature")
    for _ in range(3):
        with pytest.raises(chill.PhotoPending): await chill.photo(d)
        assert len(calls) == 1 and not chill._fetches[1][1].done()
    task = chill._fetches[1][1]
    # A stale request start must not expire a just-completed slow download.
    chill._recent[1] = (-1000, "nature", None)
    release.set()
    await task
    info = await chill.photo(d)
    assert chill.photo_path(1, info["sha256"]).is_file()
    assert await chill.photo(d) == info and calls == ["nature"]
    assert not chill._fetches


@pytest.mark.asyncio
async def test_disconnected_client_does_not_cancel_shared_fetch(db, monkeypatch):
    import asyncio
    release = asyncio.Event()
    async def download(topic):
        await release.wait()
        return image()
    monkeypatch.setattr(chill, "download", download)
    d = SimpleNamespace(id=1, device_id="leap-papa", chill_keyword="nature")
    request = asyncio.create_task(chill.photo(d))
    while 1 not in chill._fetches: await asyncio.sleep(0)
    task = chill._fetches[1][1]
    request.cancel()
    with pytest.raises(asyncio.CancelledError): await request
    assert not task.cancelled()
    release.set()
    await task
    assert await chill.photo(d)


@pytest.mark.asyncio
async def test_background_fetch_shutdown_and_topic_change(db, monkeypatch):
    import asyncio
    release = asyncio.Event()
    calls = []
    async def download(topic):
        calls.append(topic)
        await release.wait()
        return image()
    monkeypatch.setattr(chill, "download", download)
    monkeypatch.setattr(chill, "PHOTO_RESPONSE_WAIT", .01)
    d = SimpleNamespace(id=1, device_id="leap-papa", chill_keyword="nature")
    with pytest.raises(chill.PhotoPending): await chill.photo(d)
    d.chill_keyword = "forest"
    with pytest.raises(chill.PhotoPending): await chill.photo(d)
    assert calls == ["nature"]
    release.set()
    await chill._fetches[1][1]
    await chill.photo(d)
    assert calls == ["nature", "forest"]
    release.clear()
    d.chill_keyword = "ocean"
    with pytest.raises(chill.PhotoPending): await chill.photo(d)
    task = chill._fetches[1][1]
    await chill.shutdown()
    assert task.cancelled() and not chill._fetches


def test_device_gets_prompt_pending_then_completed_photo(client, db, monkeypatch):
    import asyncio
    from threading import Event
    release = Event()
    calls = []
    async def download(topic):
        calls.append(topic)
        while not release.is_set(): await asyncio.sleep(.001)
        return image()
    monkeypatch.setattr(chill, "download", download)
    monkeypatch.setattr(chill, "PHOTO_RESPONSE_WAIT", .01)
    db.add(Device(device_id="slow-photo", name="Photos", content_selection=[chill.PACKAGE_ID]))
    db.commit()
    response = client.get("/api/v1/devices/slow-photo/chill/photo")
    assert response.status_code == 503 and response.headers["retry-after"] == "10"
    assert response.headers["cache-control"] == "no-store"
    assert "vorbereitet" in response.json()["detail"]
    release.set()
    monkeypatch.setattr(chill, "PHOTO_RESPONSE_WAIT", 1)
    response = client.get("/api/v1/devices/slow-photo/chill/photo")
    assert response.status_code == 200 and calls == ["nature"]
    assert client.get(response.json()["url"]).status_code == 200


@pytest.mark.asyncio
async def test_total_upstream_budget_still_bounds_stalled_download(db, monkeypatch, caplog):
    import asyncio
    cancelled = asyncio.Event()
    async def stuck(topic):
        try: await asyncio.Event().wait()
        finally: cancelled.set()
    monkeypatch.setattr(chill, "download", stuck)
    monkeypatch.setattr(chill, "PRIMARY_ATTEMPT_TIMEOUT", .01)
    d = SimpleNamespace(id=1, device_id="leap-papa", chill_keyword="nature")
    with pytest.raises(TimeoutError): await chill.photo(d)
    assert cancelled.is_set() and not chill._fetches
    assert "stage=download error=TimeoutError" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "status", "decode"])
async def test_picsum_fallback_after_primary_failure(db, monkeypatch, failure):
    import asyncio
    calls = []
    async def primary(topic):
        calls.append(("loremflickr", topic))
        if failure == "timeout": await asyncio.Event().wait()
        if failure == "status":
            httpx.Response(503, request=httpx.Request("GET", "https://loremflickr.com/photo")).raise_for_status()
        return b"invalid JPEG"
    async def fallback():
        calls.append(("picsum", None))
        return image()
    monkeypatch.setattr(chill, "download", primary)
    monkeypatch.setattr(chill, "download_picsum", fallback)
    monkeypatch.setattr(chill, "PRIMARY_ATTEMPT_TIMEOUT", .01)
    d = SimpleNamespace(id=1, device_id="leap-papa", chill_keyword="forest")
    info = await chill.photo(d)
    assert info["source"] == "picsum" and info["keywordApplied"] is False
    assert calls == [("loremflickr", "forest"), ("picsum", None)]
    with Image.open(chill.photo_path(1, info["sha256"])) as picture:
        assert picture.size == (428, 142)


@pytest.mark.asyncio
async def test_fallback_cooldown_and_primary_recovery(db, monkeypatch):
    import time
    calls = []
    healthy = False
    async def primary(topic):
        calls.append(("loremflickr", topic))
        if not healthy: raise httpx.ConnectError("offline")
        return image()
    async def fallback():
        calls.append(("picsum", None))
        return image()
    monkeypatch.setattr(chill, "download", primary)
    monkeypatch.setattr(chill, "download_picsum", fallback)
    for id in (1, 2):
        info = await chill.photo(SimpleNamespace(id=id, device_id=f"leap-{id}", chill_keyword="ocean"))
        assert info["source"] == "picsum"
    assert calls == [("loremflickr", "ocean"), ("picsum", None), ("picsum", None)]
    healthy = True
    chill._primary_retry_at = time.monotonic() - 1
    info = await chill.photo(SimpleNamespace(id=3, device_id="leap-3", chill_keyword="forest"))
    assert info["source"] == "loremflickr" and info["keywordApplied"] is True
    assert calls[-1] == ("loremflickr", "forest") and chill._primary_retry_at == 0


@pytest.mark.asyncio
async def test_both_sources_fail_preserves_previous_photo(db, monkeypatch):
    async def primary(topic): return image()
    monkeypatch.setattr(chill, "download", primary)
    d = SimpleNamespace(id=1, device_id="leap-papa", chill_keyword="nature")
    info = await chill.photo(d)
    original = chill.photo_path(1, info["sha256"]).read_bytes()
    async def fail(topic): raise httpx.ConnectError("offline")
    async def corrupt(): return b"not a JPEG"
    monkeypatch.setattr(chill, "download", fail)
    monkeypatch.setattr(chill, "download_picsum", corrupt)
    chill._recent.clear()
    with pytest.raises(httpx.ConnectError): await chill.photo(d)
    assert chill.photo_path(1, info["sha256"]).read_bytes() == original


@pytest.mark.asyncio
async def test_picsum_uses_its_own_bounded_redirect_hosts(monkeypatch):
    calls = []
    constructor = httpx.AsyncClient
    def respond(request):
        calls.append(request)
        if request.url.host == "picsum.photos":
            assert request.url.path == "/428/142" and "random" in request.url.params
            return httpx.Response(302, headers={"location":"https://fastly.picsum.photos/id/42/428/142.jpg?hmac=example"})
        return httpx.Response(200, headers={"content-type":"image/jpeg"}, content=image())
    monkeypatch.setattr(chill.httpx, "AsyncClient", lambda **kw: constructor(transport=httpx.MockTransport(respond), **kw))
    await real_download_picsum()
    await real_download_picsum()
    assert calls[0].url.params["random"] != calls[2].url.params["random"]
    assert chill.safe_url(httpx.URL("https://fastly.picsum.photos/a.jpg"), "picsum")
    assert not chill.safe_url(httpx.URL("https://live.staticflickr.com/a.jpg"), "picsum")
    assert not chill.safe_url(httpx.URL("https://fastly.picsum.photos/a.jpg"), "loremflickr")
    for url in ("http://picsum.photos/a", "https://picsum.photos.evil.org/a", "https://user@picsum.photos/a", "https://picsum.photos:8443/a", "https://127.0.0.1/a"):
        assert not chill.safe_url(httpx.URL(url), "picsum")
    def blocked(request): return httpx.Response(302, headers={"location":"https://127.0.0.1/private"})
    monkeypatch.setattr(chill.httpx, "AsyncClient", lambda **kw: constructor(transport=httpx.MockTransport(blocked), **kw))
    with pytest.raises(ValueError, match="Bildweiterleitung"): await real_download_picsum()


@pytest.mark.asyncio
async def test_fallback_timeout_is_bounded(db, monkeypatch, caplog):
    import asyncio
    cancelled = asyncio.Event()
    async def primary(topic): raise httpx.ConnectError("LoremFlickr offline")
    async def fallback():
        try: await asyncio.Event().wait()
        finally: cancelled.set()
    monkeypatch.setattr(chill, "download", primary)
    monkeypatch.setattr(chill, "download_picsum", fallback)
    monkeypatch.setattr(chill, "FALLBACK_ATTEMPT_TIMEOUT", .01)
    d = SimpleNamespace(id=1, device_id="leap-papa", chill_keyword="nature")
    with pytest.raises(httpx.ConnectError): await chill.photo(d)
    assert cancelled.is_set() and not chill._fetches
    assert "source=picsum stage=download error=TimeoutError" in caplog.text
