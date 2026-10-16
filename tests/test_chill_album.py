from io import BytesIO
from PIL import Image
from sqlalchemy import select
from app.models import AssetPackage, ChillPhoto, Device
from app.services import distribution as assets
from app.services import chill_album
from test_app import make_device


def picture(color="red", size=(800, 600)):
    out = BytesIO()
    image = Image.new("RGB", size, color)
    exif = Image.Exif(); exif[270] = "private original metadata"
    image.save(out, "JPEG", exif=exif)
    return out.getvalue()


def upload(client, device, raw=None):
    return client.post(f"/devices/{device.id}/chill/album/upload", follow_redirects=False,
                       files=[("files", ("Mein Foto.jpg", raw if raw is not None else picture(), "image/jpeg"))])


def sync(client, device, firmware="1.1.2"):
    return client.post(f"/api/v1/devices/{device.device_id}/sync", json={"firmwareVersion": firmware}).json()


def test_upload_compacts_and_syncs_only_selected_device(client, db):
    first = make_device(db)
    second = Device(device_id="other", name="Other"); db.add(second); db.commit()
    before = first.config_version
    assert upload(client, first).status_code == 303
    db.refresh(first)
    assert len(first.chill_photos) == 1 and first.config_version == before + 1
    photo = db.get(ChillPhoto, first.chill_photos[0])
    assert photo.size < len(picture())
    with Image.open(assets.blob_path(photo.id)) as image:
        assert image.size == (428, 142) and not image.getexif()
        assert not image.info.get("progressive")
    plan = sync(client, first)
    assert first.chill_album_id in plan["desiredAssets"]
    assert first.chill_album_id not in sync(client, second)["desiredAssets"]
    package = db.get(AssetPackage, first.chill_album_id)
    manifest = assets.current(db, package).manifest
    assert manifest["definition"]["scene"] == "album"
    for file in manifest["files"]:
        assert client.get(file["url"]).status_code == 200
    assert {row["packageId"] for row in sync(client, first, "1.1.1")["blockedAssets"]} == {package.id}
    assert "Eigene Chill-Bilder" in client.get(f"/devices/{first.id}").text
    assert client.get(f"/devices/{first.id}/chill/album").status_code == 200


def test_shared_library_selection_duplicate_and_independent_albums(client, db):
    first = make_device(db)
    assert upload(client, first).status_code == 303
    assert upload(client, first, picture("blue")).status_code == 303
    assert len(first.chill_photos) == 2
    # Re-uploading the same pixels consumes one content-addressed library item.
    assert upload(client, first).status_code == 303
    assert len(first.chill_photos) == 2
    first_ids = list(first.chill_photos)
    client.post(f"/devices/{first.id}/duplicate", follow_redirects=False)
    copy = db.scalar(select(Device).where(Device.device_id == "leap-erik-copy"))
    assert copy.chill_album_id != first.chill_album_id and copy.chill_photos == first_ids
    assert client.post(f"/devices/{copy.id}/chill/album", data={"photo_ids": first_ids[:1]},
                       follow_redirects=False).status_code == 303
    db.refresh(first)
    assert first.chill_photos == first_ids and copy.chill_photos == first_ids[:1]
    assert len(db.scalars(select(ChillPhoto)).all()) == 2
    assert first.chill_album_id not in client.get(f"/devices/{copy.id}").text


def test_invalid_upload_selection_and_album_limit(client, db, monkeypatch):
    device = make_device(db)
    before = device.config_version
    assert upload(client, device, b"broken").status_code == 422
    assert not device.chill_album_id and device.config_version == before
    monkeypatch.setattr(chill_album, "MAX_UPLOAD", 8)
    assert upload(client, device, b"012345678").status_code == 413
    assert client.post(f"/devices/{device.id}/chill/album", data={"photo_ids": ["unknown"]}).status_code == 422
    assert client.post(f"/devices/{device.id}/chill/album", data={"photo_ids": [str(i) for i in range(25)]}).status_code == 422
    assert client.get("/chill/photos/not-a-hash.jpg").status_code == 404
    assert client.get("/devices/9999/chill/album").status_code == 404
