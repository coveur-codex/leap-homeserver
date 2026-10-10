import json
from importlib import import_module
from alembic.migration import MigrationContext
from alembic.operations import Operations
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, text
from app.core.games import DEFAULT_GAMES
from app.models import Device
from test_app import make_device


def test_selection_saved_synced_and_duplicated(client, db):
    d = make_device(db)
    before = d.config_version
    form = {"name": "Erik", "age": 9, "avatar": "dragon", "enabled": "on",
            "page_ids": ["home", "games"], "game_settings": "true",
            "game_ids": ["snake", "kitchen", "snake"]}
    assert client.post(f"/devices/{d.id}", data=form, follow_redirects=False).status_code == 303
    db.refresh(d)
    assert d.enabled_games == ["snake", "kitchen"]
    assert d.config_version == before + 1
    plan = client.post("/api/v1/devices/leap-erik/sync", json={"firmwareVersion": "1.0.0", "installedAssets": {}}).json()
    config = client.get(plan["configUrl"]).json()
    assert config["configVersion"] == d.config_version
    assert {g["id"] for g in config["games"] if g["enabled"]} == {"snake", "kitchen"}
    editor = BeautifulSoup(client.get(f"/devices/{d.id}").text, "html.parser")
    assert {tag["value"] for tag in editor.select('input[name="game_ids"][checked]')} == {"snake", "kitchen"}
    assert editor.select('[data-game-open="snake"]')
    assert not editor.select('[data-game-open="pet"]')
    client.post(f"/devices/{d.id}/duplicate", follow_redirects=False)
    copy = db.query(Device).filter_by(device_id="leap-erik-copy").one()
    assert copy.enabled_games == d.enabled_games
    copy.enabled_games = []
    db.commit()
    assert d.enabled_games == ["snake", "kitchen"]
    form.pop("game_ids")
    assert client.post(f"/devices/{d.id}", data=form, follow_redirects=False).status_code == 303
    assert not any(g["enabled"] for g in client.get(plan["configUrl"]).json()["games"])
    assert "Keine Spiele freigegeben." in client.get(f"/devices/{d.id}").text


def test_invalid_selection_and_legacy_form(client, db):
    d = make_device(db)
    before = d.config_version
    form = {"name": "Test", "age": 9, "avatar": "dragon", "game_settings": "true", "game_ids": ["unknown"]}
    assert client.post(f"/devices/{d.id}", data=form).status_code == 422
    db.refresh(d)
    assert d.config_version == before and d.enabled_games == DEFAULT_GAMES
    d.enabled_games = ["snake"]
    db.commit()
    form.pop("game_settings")
    form.pop("game_ids")
    assert client.post(f"/devices/{d.id}", data=form, follow_redirects=False).status_code == 303
    db.refresh(d)
    assert d.enabled_games == ["snake"]


def test_migration_preserves_games_and_fresh_schema(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    migration = import_module("migrations.versions.0010_enabled_games")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE devices (id INTEGER PRIMARY KEY, config_version INTEGER NOT NULL)"))
        connection.execute(text("INSERT INTO devices VALUES (1,7)"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        games, version = connection.execute(text("SELECT enabled_games, config_version FROM devices")).one()
        assert json.loads(games) == [gid for gid in DEFAULT_GAMES if gid != "dragon_run"] and version == 8
        # Fresh installs already have the new column through metadata in 0001.
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert json.loads(connection.execute(text("SELECT enabled_games FROM devices")).scalar()) == [gid for gid in DEFAULT_GAMES if gid != "dragon_run"]


def test_dragon_run_selection_and_preview(client, db):
    d = make_device(db)
    form = {"name": "Erik", "age": 9, "avatar": "dragon", "enabled": "on",
            "page_ids": ["games"], "game_settings": "true", "game_ids": ["dragon_run"]}
    assert client.post(f"/devices/{d.id}", data=form, follow_redirects=False).status_code == 303
    config = client.get("/api/v1/devices/leap-erik/config").json()
    assert [g["id"] for g in config["games"] if g["enabled"]] == ["dragon_run"]
    html = BeautifulSoup(client.get(f"/devices/{d.id}").text, "html.parser")
    assert html.select('[data-game-open="dragon"]')
    assert html.select('canvas[data-dragon-canvas]')[0]["width"] == "342"
    assert not html.select('[data-game-open="snake"]')
    d.enabled_games = ["snake"]
    db.commit()
    assert not BeautifulSoup(client.get(f"/devices/{d.id}").text, "html.parser").select('[data-game-open="dragon"]')
