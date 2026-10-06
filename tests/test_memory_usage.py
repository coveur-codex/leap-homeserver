from importlib import import_module

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

from app.models import Device
from app.services.devices import initialize_pages


def make_device(db):
    device = Device(device_id="leap-memory", name="Memory")
    initialize_pages(device)
    db.add(device)
    db.commit()
    return device


def test_checkin_memory_and_pages(client, db):
    device = make_device(db)
    memory = {
        "flash": {"used": 2 * 1048576, "total": 4 * 1048576},
        "littlefs": {"used": 838861, "total": 2 * 1048576},
        "psram": {"used": 0, "total": 0},
    }
    response = client.post("/api/v1/devices/leap-memory/checkin", json={
        "firmwareVersion": "test", "freeFlash": 2 * 1048576 - 838861, "memory": memory,
    })
    assert response.status_code == 200
    db.expire_all()
    assert device.memory_usage == memory
    assert device.free_flash == 2 * 1048576 - 838861
    for url in ("/devices", f"/devices/{device.id}"):
        page = client.get(url)
        assert page.status_code == 200
        assert "2,0 / 4,0 MB" in page.text
        assert "0,8 / 2,0 MB" in page.text
        assert "Nicht verfügbar" in page.text
        assert "letzter Gerätekontakt" in page.text
    # Old firmware remains supported; its check-in must not refresh stale measurements.
    assert client.post("/api/v1/devices/leap-memory/checkin", json={"freeFlash": 123}).status_code == 200
    db.expire_all()
    assert device.memory_usage is None and device.free_flash == 123
    assert "Noch keine Speicherwerte gemeldet" in client.get("/devices").text


@pytest.mark.parametrize("usage", [
    {"used": -1, "total": 10}, {"used": 11, "total": 10},
    {"used": 0, "total": -1}, {"used": 0, "total": 4294967296},
])
def test_invalid_memory_rejected(client, db, usage):
    device = make_device(db)
    snapshot = {name: {"used": 0, "total": 0} for name in ("flash", "littlefs", "psram")}
    snapshot["littlefs"] = usage
    assert client.post("/api/v1/devices/leap-memory/checkin", json={"memory": snapshot}).status_code == 422
    db.expire_all()
    assert device.last_seen is None


def test_memory_migration_preserves_existing_device(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    migration = import_module("migrations.versions.0007_memory_usage")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE devices (id INTEGER PRIMARY KEY, name TEXT)"))
        connection.execute(text("INSERT INTO devices VALUES (1, 'Existing')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()
        assert connection.execute(text("SELECT name, memory_usage FROM devices")).one() == ("Existing", None)
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert connection.execute(text("SELECT name FROM devices")).scalar() == "Existing"
