from bs4 import BeautifulSoup
from app.models import Device
from app.services.devices import initialize_pages


def test_time_config_preview_and_sound(client, db):
    device = Device(device_id="time-test", name="Zeit", accent_color="#ff9900")
    initialize_pages(device)
    db.add(device)
    db.commit()
    config = client.get("/api/v1/devices/time-test/config").json()
    assert next(p for p in config["pages"] if p["id"] == "time")["enabled"]
    assert config["notificationSounds"]["time"] is True
    page = BeautifulSoup(client.get(f"/devices/{device.id}").text, "html.parser")
    assert page.select_one('[data-preview-card="ZEIT"]')
    assert "#ff9900" in page.select_one(".leap-preview")["style"]
    assert page.select_one('[name="sound_time"]').has_attr("checked")
    client.post(f"/devices/{device.id}", data={"name": "Zeit", "age": 9, "avatar": "dragon",
                "page_ids": ["home"], "notification_settings": "true"})
    config = client.get("/api/v1/devices/time-test/config").json()
    assert not next(p for p in config["pages"] if p["id"] == "time")["enabled"]
    assert config["notificationSounds"]["time"] is False
    assert 'data-preview-card="ZEIT"' not in client.get(f"/devices/{device.id}").text


def test_existing_device_migration_preserves_order(db):
    import importlib.util
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from pathlib import Path
    device = Device(device_id="old-time", name="Alt")
    initialize_pages(device)
    device.pages = [p for p in device.pages if p.page_id != "time"]
    device.pages[0].position = 42
    db.add(device)
    db.commit()
    spec = importlib.util.spec_from_file_location("time_migration", Path(__file__).parents[1] / "migrations/versions/0018_time_module.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    connection = db.connection()
    with Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()
        migration.upgrade()  # no duplicate page if migration is replayed
    db.expire_all()
    page = next(p for p in device.pages if p.page_id == "time")
    assert page.enabled and page.position == 43
    assert next(p for p in device.pages if p.page_id == "home").position == 42
