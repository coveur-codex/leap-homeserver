import hashlib
from bs4 import BeautifulSoup
from sqlalchemy import select

from app.models import AssetPackage, CommunicationMessage, Device
from app.services.communication import PACKAGE_ID, messages
from app.services.devices import initialize_pages
from app.services.distribution import ensure_packages


def create_device(db):
    device = Device(device_id="leap-chat", name="Chat", child_name="Mia")
    initialize_pages(device)
    db.add(device)
    db.commit()
    return device


def sync(client, installed=None):
    response = client.post("/api/v1/devices/leap-chat/sync", json={"firmwareVersion": "1.0.0", "installedAssets": installed or {}})
    assert response.status_code == 200
    return response.json()


def payload(client, version):
    manifest = client.get(f"/api/v1/packages/{PACKAGE_ID}/versions/{version}/manifest").json()
    file = next(f for f in manifest["files"] if f["path"] == "messages.json")
    response = client.get(file["url"])
    assert hashlib.sha256(response.content).hexdigest() == file["sha256"]
    return response.json()["messages"]


def save(client, db, **fields):
    expected = db.get(AssetPackage, PACKAGE_ID).current_version
    return client.post("/communication/messages", data={"expected": expected, "text": "Test", "position": 1, "active": "on", **fields}, follow_redirects=False)


def test_device_switch_controls_config_preview_and_sync(client, db):
    device = create_device(db)
    config_url = "/api/v1/devices/leap-chat/config"
    assert client.get(config_url).json()["communicationEnabled"] is True
    assert PACKAGE_ID in sync(client)["desiredAssets"]
    html = BeautifulSoup(client.get(f"/devices/{device.id}").text, "html.parser")
    assert html.select_one('[data-preview-card="KOMMUNIKATION"] img')
    assert html.select_one('[name="communication_enabled"]').has_attr("checked")
    form = {"name": "Chat", "age": 8, "avatar": "dragon", "enabled": "on", "page_ids": ["home", "communication"],
            "page_positions": [9 if p.page_id == "communication" else p.position for p in device.pages]}
    assert client.post(f"/devices/{device.id}", data=form).status_code == 200
    config = client.get(config_url).json()
    assert config["communicationEnabled"] is False
    assert not next(p for p in config["pages"] if p["id"] == "communication")["enabled"]
    assert 'data-preview-card="KOMMUNIKATION"' not in client.get(f"/devices/{device.id}").text
    assert PACKAGE_ID not in sync(client, {PACKAGE_ID: 1})["desiredAssets"]
    client.post(f"/devices/{device.id}/duplicate", follow_redirects=False)
    assert db.scalar(select(Device).where(Device.device_id == "leap-chat-copy")).communication_enabled is False
    form["communication_enabled"] = "on"
    client.post(f"/devices/{device.id}", data=form)
    page = next(p for p in client.get(config_url).json()["pages"] if p["id"] == "communication")
    assert page["enabled"] and page["order"] == 9
    assert PACKAGE_ID in sync(client)["desiredAssets"]


def test_message_lifecycle_versioning_and_conflict(client, db):
    create_device(db)
    initial = payload(client, 1)
    assert len(initial) == 10
    assert client.get('/communication').status_code == 200
    assert save(client, db, text="Neu!", symbol="✓", position=2).status_code == 303
    new = next(m for m in messages(db) if m.text == "Neu!")
    assert any(m["id"] == new.id for m in payload(client, 2))
    assert save(client, db, message_id=new.id, text="Geändert", position=1).status_code == 303
    assert payload(client, 3) == sorted(payload(client, 3), key=lambda m: (m["order"], m["id"]))
    assert save(client, db, message_id=new.id, text="Inaktiv", active="false").status_code == 303
    assert new.id not in {m["id"] for m in payload(client, 4)}
    assert "Inaktiv" not in client.get('/devices/1').text
    assert save(client, db, message_id=new.id, expected=2, text="Veraltet").status_code == 409
    assert db.get(CommunicationMessage, new.id).text == "Inaktiv"
    assert save(client, db, message_id=new.id, text="Wieder aktiv", active="on").status_code == 303
    plan = sync(client, {PACKAGE_ID: 4})
    assert plan["desiredAssets"][PACKAGE_ID] == 5
    assert any(p["packageId"] == PACKAGE_ID for p in plan["assetUpdates"])
    assert not any(p["packageId"] == PACKAGE_ID for p in sync(client, {PACKAGE_ID: 5})["assetUpdates"])
    assert client.post(f"/communication/messages/{new.id}/delete", data={"expected": 5}, follow_redirects=False).status_code == 303
    assert new.id not in {m["id"] for m in payload(client, 6)}
    assert payload(client, 1) == initial


def test_validation_empty_list_and_generated_asset_protection(client, db):
    for fields in [{"text": " "}, {"text": "x"*121}, {"symbol": "x"*17}, {"position": 0}]:
        assert save(client, db, **fields).status_code == 422
    assert db.get(AssetPackage, PACKAGE_ID).current_version == 1
    assert save(client, db, text='<script>alert(1)</script>').status_code == 303
    assert '&lt;script&gt;' in client.get('/communication').text
    for message in messages(db):
        expected = db.get(AssetPackage, PACKAGE_ID).current_version
        assert client.post(f"/communication/messages/{message.id}/delete", data={"expected": expected}, follow_redirects=False).status_code == 303
    version = db.get(AssetPackage, PACKAGE_ID).current_version
    ensure_packages(db)
    assert messages(db) == [] and payload(client, version) == []
    assert client.post(f'/assets/{PACKAGE_ID}/definition', data={"expected": version, "definition": '{}'}).status_code == 422
    assert client.post(f'/assets/{PACKAGE_ID}/files/delete', data={"expected": version, "path": 'messages.json'}).status_code == 422
    assert client.post('/assets', data={"package_id": "another-chat", "kind": "communication", "name": "Chat"}).status_code == 422
    assert 'Dateien oder ZIP hinzufügen' not in client.get(f'/assets/{PACKAGE_ID}').text


def test_migration_preserves_existing_devices_and_page_order(tmp_path):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from importlib import import_module
    from sqlalchemy import create_engine, text

    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE devices (id INTEGER PRIMARY KEY, config_version INTEGER NOT NULL)"))
        connection.execute(text("CREATE TABLE device_pages (id INTEGER PRIMARY KEY, device_id INTEGER, page_id TEXT, title TEXT, enabled BOOLEAN, position INTEGER, settings JSON)"))
        connection.execute(text("INSERT INTO devices VALUES (1,7), (2,3)"))
        connection.execute(text("INSERT INTO device_pages VALUES (1,1,'home','Home',1,5,'{}')"))
        with Operations.context(MigrationContext.configure(connection)):
            import_module('migrations.versions.0006_communication').upgrade()
        assert connection.execute(text("SELECT communication_enabled, config_version FROM devices ORDER BY id")).all() == [(1,8), (1,4)]
        assert connection.execute(text("SELECT position FROM device_pages WHERE page_id='home'")).scalar() == 5
        assert connection.execute(text("SELECT device_id, position, enabled FROM device_pages WHERE page_id='communication' ORDER BY device_id")).all() == [(1,6,1), (2,1,1)]
