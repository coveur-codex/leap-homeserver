import json
from importlib import import_module

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, text

from app.models import Device
from app.services.devices import initialize_pages


def make_device(db):
    device = Device(device_id="leap-reader", name="Lesekind")
    initialize_pages(device)
    db.add(device)
    db.commit()
    return device


def settings(client, device_id="leap-reader"):
    config = client.get(f"/api/v1/devices/{device_id}/config").json()
    return config, next(page for page in config["pages"] if page["id"] == "learning")


def form(**extra):
    return {"name": "Lesekind", "age": 7, "avatar": "dragon", "enabled": "on",
            "page_ids": ["home", "learning"], "learning_settings": "true",
            "learning_applications": ["math_lab", "syllable_trainer"],
            "learning_levels": [1, 2], "learning_mode": 1, "learning_length": 15,
            "learning_random": "on", "learning_seconds": 10,
            "learning_syllables": '[{"text":"WE","level":1}]',
            "learning_words": '[{"word":"WIESE","syllables":["WIE","SE"],"level":3}]', **extra}


def test_learning_device_form_config_and_existing_sync(client, db):
    device = make_device(db)
    config, page = settings(client)
    assert page["enabled"] and page["title"] == "Lernwelt"
    trainer = page["settings"]["syllableTrainer"]
    assert trainer["autoSeconds"] == 0 and trainer["sessionLength"] == 10
    assert trainer["levels"] == [1, 2, 3]
    html = BeautifulSoup(client.get(f"/devices/{device.id}").text, "html.parser")
    assert html.select_one('[data-preview-card="LERNWELT"]')
    assert html.select_one('[name="page_ids"][value="learning"]').has_attr("checked")
    assert html.select_one('[name="learning_applications"][value="syllable_trainer"]').has_attr("checked")
    before = config["configVersion"]
    response = client.post(f"/devices/{device.id}", data=form(), follow_redirects=False)
    assert response.status_code == 303
    config, page = settings(client)
    assert config["configVersion"] == before + 1
    trainer = page["settings"]["syllableTrainer"]
    assert (trainer["levels"], trainer["defaultMode"], trainer["sessionLength"], trainer["autoSeconds"]) == ([1, 2], 1, 15, 10)
    assert trainer["words"][0]["syllables"] == ["WIE", "SE"]
    assert trainer["syllables"][0]["text"] == "WE"
    assert not any(game["id"] == "math_lab" for game in config["games"])
    plan = client.post("/api/v1/devices/leap-reader/sync", json={"firmwareVersion": "1.9.0", "installedAssets": {}}).json()
    assert plan["configVersion"] == config["configVersion"]
    assert client.get(plan["configUrl"]).json() == config
    # The same JSON round-trip is the offline snapshot representation.
    assert json.loads(json.dumps(config))["pages"] == config["pages"]


def test_permissions_and_preservation_on_unrelated_edits_and_copy(client, db):
    device = make_device(db)
    learning = next(page for page in device.pages if page.page_id == "learning")
    device.math_lab = {"targets": [9, 10]}
    learning.settings = {**learning.settings, "future": {"keep": True}}
    db.commit()
    assert client.post(f"/devices/{device.id}", data=form(learning_applications=["syllable_trainer"])).status_code == 200
    _, page = settings(client)
    assert page["settings"]["applications"] == [{"id": "math_lab", "enabled": False}, {"id": "syllable_trainer", "enabled": True}]
    assert settings(client)[0]["mathLab"]["targets"] == [9, 10]
    assert page["settings"]["future"] == {"keep": True}
    previous = page["settings"]
    assert client.post(f"/devices/{device.id}", data={"name": "Neu", "age": 8, "avatar": "frog", "enabled": "on", "page_ids": ["home"]}).status_code == 200
    _, page = settings(client)
    assert not page["enabled"] and page["settings"] == previous
    assert client.post(f"/devices/{device.id}/duplicate", follow_redirects=False).status_code == 303
    _, copied = settings(client, "leap-reader-copy")
    assert not copied["enabled"] and copied["settings"] == previous
    assert settings(client, "leap-reader-copy")[0]["mathLab"]["targets"] == [9, 10]


@pytest.mark.parametrize("extra", [
    {"learning_levels": []}, {"learning_levels": [4]}, {"learning_mode": 3},
    {"learning_length": 50}, {"learning_seconds": 1}, {"learning_applications": ["unknown"]},
    {"learning_syllables": "not json"}, {"learning_words": "{}"},
    {"learning_words": '[{"word":"BANANE","syllables":["BA","NA"]}]'},
    {"learning_words": '[{"word":"MAMA","syllables":["MAMA"]}]'},
    {"learning_words": '[{"word":"Mama","syllables":["Ma","ma"]}]'},
    {"learning_syllables": '[{"text":"SCHMETT","level":3}]'},
    {"learning_syllables": json.dumps([{"text": "WE"}] * 33)},
    {"learning_words": " " * 16001},
])
def test_invalid_content_does_not_change_config(client, db, extra):
    device = make_device(db)
    previous = settings(client)[0]
    response = client.post(f"/devices/{device.id}", data=form(**extra))
    assert response.status_code == 422
    assert settings(client)[0] == previous


def test_learning_migration_preserves_settings_order_and_enablement(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    migration = import_module("migrations.versions.0026_learning")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE devices (id INTEGER PRIMARY KEY, config_version INTEGER NOT NULL, enabled_games JSON, math_lab JSON)"))
        connection.execute(text("CREATE TABLE device_pages (id INTEGER PRIMARY KEY, device_id INTEGER, page_id TEXT, title TEXT, enabled BOOLEAN, position INTEGER, settings JSON)"))
        connection.execute(text("INSERT INTO devices VALUES (1,7,'[\"math_lab\",\"snake\"]','{\"targets\":[9,10]}'), (2,3,'[\"snake\"]','{\"targets\":[5]}')"))
        connection.execute(text("INSERT INTO device_pages VALUES (1,1,'games','Spiele',1,5,:settings), (2,2,'games','Spiele',0,9,'{}')"), {"settings": json.dumps({"mathLab": {"targets": [9, 10]}, "other": True})})
        old = connection.execute(text("SELECT * FROM device_pages ORDER BY id")).all()
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()  # No duplicate pages or repeated config bumps.
        assert connection.execute(text("SELECT * FROM device_pages WHERE page_id='games' ORDER BY id")).all() == old
        assert connection.execute(text("SELECT config_version FROM devices ORDER BY id")).all() == [(8,), (4,)]
        assert connection.execute(text("SELECT device_id, position, enabled FROM device_pages WHERE page_id='learning' ORDER BY device_id")).all() == [(1, 6, 1), (2, 10, 0)]
        preserved = json.loads(connection.execute(text("SELECT settings FROM device_pages WHERE page_id='learning' AND device_id=1")).scalar())
        assert preserved["applications"][0] == {"id": "math_lab", "enabled": True}
        other = json.loads(connection.execute(text("SELECT settings FROM device_pages WHERE page_id='learning' AND device_id=2")).scalar())
        assert other["applications"][0] == {"id": "math_lab", "enabled": False}
        assert json.loads(connection.execute(text("SELECT math_lab FROM devices WHERE id=1")).scalar()) == {"targets": [9, 10]}
        assert json.loads(connection.execute(text("SELECT enabled_games FROM devices WHERE id=1")).scalar()) == ["math_lab", "snake"]
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert connection.execute(text("SELECT * FROM device_pages ORDER BY id")).all() == old
