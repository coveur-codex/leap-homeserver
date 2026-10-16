from io import BytesIO
from PIL import Image
from sqlalchemy import select
from app.models import AssetPackage, CommunicationMessage, Device
from app.services import distribution as assets
from app.services import communication_avatars as portraits
from test_app import make_device


def image(color, size=(80, 80)):
    out = BytesIO(); Image.new("RGBA", size, color).save(out, "PNG"); return out.getvalue()


def test_snapshots_prefer_communication_picture_and_preserve_old_portraits(client, db):
    sender = make_device(db)
    package = AssetPackage(id="avatar-custom", name="Custom", kind="avatar", current_version=0)
    db.add(package); db.flush()
    files = {"preview.png": assets.store_bytes(image("blue")),
             "data/pet/pagestatics/communication.png": assets.store_bytes(image("red", (80, 100)))}
    assets.publish(db, package, files, {"preview": "preview.png"}, 0)
    sender.avatar = package.id; db.commit()
    template = db.scalar(select(CommunicationMessage.id))
    event = client.post("/api/v1/devices/leap-erik/communication/messages",
                        json={"templateId": template, "eventId": "first"}).json()["message"]
    digest = event["avatarImage"]
    bank = db.get(AssetPackage, portraits.PACKAGE_ID)
    current = assets.current(db, bank)
    path = digest + ".png"
    info = assets.file_map(current)[path]
    with Image.open(assets.blob_path(info["sha256"])) as thumb:
        assert thumb.size == (48, 48) and thumb.getpixel((24, 24)) == (255, 0, 0, 255)
        assert thumb.getpixel((0, 0))[3] == 0 # aspect ratio preserved
    previous = bank.current_version
    assert not portraits.ensure_package(db) and bank.current_version == previous
    files["data/pet/pagestatics/communication.png"] = assets.store_bytes(image("green"))
    assets.publish(db, package, files, {"preview": "preview.png"}, package.current_version)
    assert portraits.ensure_package(db)
    db.commit()
    assert path in assets.file_map(assets.current(db, bank))
    history = client.get("/api/v1/devices/leap-erik/communication/messages").json()["messages"]
    assert history[0]["avatarImage"] == digest
    sender.avatar = "dragon"; db.commit()
    assert client.post("/api/v1/devices/leap-erik/communication/messages", json={
        "templateId": template, "eventId": "first"}).json()["message"] == event


def test_shared_package_reaches_every_device_and_is_protected(client, db):
    sender = make_device(db)
    other = Device(device_id="other", name="Other", avatar="frog", communication_enabled=False)
    db.add(other); db.commit()
    for device in (sender, other):
        plan = client.post(f"/api/v1/devices/{device.device_id}/sync", json={"firmwareVersion": "1.1.2"}).json()
        assert portraits.PACKAGE_ID in plan["desiredAssets"]
    bank = db.get(AssetPackage, portraits.PACKAGE_ID)
    files = assets.file_map(assets.current(db, bank))
    assert files and all(f.endswith(".png") for f in files)
    assert client.post(f"/assets/{bank.id}/delete", data={"expected": bank.current_version, "confirmed": "true"}).status_code == 422
    assert client.post(f"/api/v1/devices/{sender.device_id}/communication/messages", json={
        "templateId": "icon-smile", "eventId": "forged", "avatarImage": "a"*64}).status_code == 422
