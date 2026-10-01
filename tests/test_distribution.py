import hashlib
import json
import subprocess
import os
from pathlib import Path

from sqlalchemy import select
from app.models import AssetPackage, AssetVersion, Device, FirmwareRelease, QuizCatalog, QuizQuestion
from app.services.devices import initialize_pages
from app.services import distribution as service


def device(db, channel="stable"):
    d = Device(device_id="leap-test", name="Test", firmware_channel=channel)
    initialize_pages(d); db.add(d); db.commit()
    return d


def create(client, key, kind="chill"):
    response = client.post("/assets", data={"package_id": key, "name": key, "kind": kind}, follow_redirects=False)
    assert response.status_code == 303, response.text


def sync(client, assets=None, firmware="0.8.0"):
    response = client.post("/api/v1/devices/leap-test/sync", json={"firmwareVersion": firmware, "installedAssets": assets or {}})
    assert response.status_code == 200, response.text
    return response.json()


def event(client, plan, **data):
    return client.post(f'/api/v1/devices/leap-test/sync/{plan["syncId"]}/events', json=data)


def binary():
    data = bytearray(256)
    data[0], data[1], data[12] = 0xE9, 1, 9
    return bytes(data)


def upload_firmware(client, version, channel):
    return client.post("/firmware", data={"version": version, "channel": channel, "notes": "Test"}, files={"file": ("leap.bin", binary())}, follow_redirects=False)


def test_immutable_versions_hashes_and_files(client, db):
    create(client, "chill-ocean")
    upload = lambda value, version: client.post("/assets/chill-ocean/files", data={"expected": version}, files={"files": ("fish.png", value)}, follow_redirects=False)
    assert upload(b"first", 1).status_code == 303
    assert upload(b"second", 2).status_code == 303
    assert upload(b"stale", 1).status_code == 409
    for version, content in [(2, b"first"), (3, b"second")]:
        manifest = client.get(f"/api/v1/packages/chill-ocean/versions/{version}/manifest").json()
        file = next(f for f in manifest["files"] if f["path"] == "fish.png")
        assert file["sha256"] == hashlib.sha256(content).hexdigest()
        assert file["size"] == len(content)
        assert client.get(file["url"]).content == content
        definition = next(f for f in manifest["files"] if f["path"] == "definition.json")
        assert client.get(definition["url"]).json()["version"] == version
    assert client.get("/assets/chill-ocean?version=2").status_code == 200
    assert client.post("/assets/chill-ocean/files", data={"expected": 3, "folder": "../escape"}, files={"files": ("x", b"x")}).status_code == 422


def test_avatar_animation_extension_does_not_mutate_old_manifest(client, db):
    create(client, "avatar-test", "avatar")
    for expected, name in [(1, "001.png"), (2, "002.png")]:
        assert client.post("/assets/avatar-test/files", data={"expected": expected, "folder": "animations/idle"}, files={"files": (name, b"frame")}, follow_redirects=False).status_code == 303
    old = client.get("/api/v1/packages/avatar-test/versions/2/manifest").json()
    new = client.get("/api/v1/packages/avatar-test/versions/3/manifest").json()
    assert old["definition"]["animations"]["idle"]["frames"] == ["animations/idle/001.png"]
    assert len(new["definition"]["animations"]["idle"]["frames"]) == 2
    assert client.post("/assets/avatar-test/files/delete", data={"expected": 3, "path": "animations/idle/001.png"}, follow_redirects=False).status_code == 303
    assert client.get("/api/v1/packages/avatar-test/versions/4/manifest").json()["definition"]["animations"]["idle"]["frames"] == ["animations/idle/002.png"]


def test_quiz_adoption_and_editor_preserve_links(client, db):
    d = device(db)
    catalog = QuizCatalog(name="Natur", questions=[QuizQuestion(question="Alt?", answers=["a", "b", "c", "d"])])
    d.quiz_catalogs.append(catalog); db.commit()
    original = catalog.questions[0].id
    assert client.get("/assets?kind=quiz").status_code == 200
    package = db.scalar(select(AssetPackage).where(AssetPackage.catalog_id == catalog.id))
    assert catalog.questions[0].id == original and catalog in d.quiz_catalogs
    page = client.get(f"/assets/{package.id}")
    assert page.status_code == 200 and "Neue Frage hinzufügen" in page.text
    response = client.post(f"/assets/{package.id}/questions", data={"expected": 1, "question": "Neu?", "answers": ["1", "2", "3", "4"]}, follow_redirects=False)
    assert response.status_code == 303, response.text
    assert package.current_version == 2
    assert len(client.get("/api/v1/devices/leap-test/quiz").json()["questions"]) == 2
    assert client.get(f"/api/v1/packages/{package.id}/versions/1/manifest").json()["definition"]["questionCount"] == 1
    assert package.id in sync(client)["desiredAssets"]


def test_config_drives_assets_and_delayed_cleanup(client, db):
    d = device(db)
    create(client, "chill-sea")
    response = client.post(f"/devices/{d.id}", data={"name": "Test", "age": 8, "avatar": "avatar-jellyfish", "enabled": "true", "distribution_settings": "true", "firmware_channel": "beta", "content_ids": ["chill-sea"]}, follow_redirects=False)
    assert response.status_code == 303
    plan = sync(client, {"avatar-dragon": 1})
    assert plan["firmwareChannel"] == "beta"
    assert plan["desiredAssets"] == {"avatar-jellyfish": 1, "chill-sea": 1}
    assert not plan["cleanupAllowed"]
    assert event(client, plan, event="boot_success", firmwareVersion="0.8.0", installedAssets={"avatar-dragon": 1}).status_code == 409
    assert event(client, plan, event="asset_installed", packageId="avatar-jellyfish", version=1).json()["cleanupAllowed"] is False
    response = event(client, plan, event="boot_success", firmwareVersion="0.8.0", installedAssets=plan["desiredAssets"])
    assert response.json()["removeVersions"] == [{"packageId": "avatar-dragon", "version": 1}]
    assert response.json()["cleanupAllowed"]
    assert event(client, plan, event="sync_success", firmwareVersion="0.8.0", installedAssets=plan["desiredAssets"]).status_code == 200
    assert client.get(f"/devices/{d.id}").status_code == 200


def test_failed_and_superseded_sync_never_allow_cleanup(client, db):
    device(db)
    plan = sync(client)
    assert event(client, plan, event="checksum_failed", message="bad hash").json()["cleanupAllowed"] is False
    assert event(client, plan, event="boot_success", firmwareVersion="0.8.0", installedAssets=plan["desiredAssets"]).status_code == 409
    newer = sync(client)
    assert event(client, plan, event="download_started").status_code == 409
    assert event(client, newer, event="download_aborted").status_code == 200


def test_firmware_channels_promotion_order_and_streaming(client, db):
    d = device(db)
    assert upload_firmware(client, "0.9.0", "beta").status_code == 303
    assert upload_firmware(client, "0.8.5", "stable").status_code == 303
    assert sync(client)["firmware"]["version"] == "0.8.5"
    d.firmware_channel = "beta"; db.commit()
    plan = sync(client)
    assert plan["firmware"]["version"] == "0.9.0"
    response = client.get(plan["firmware"]["url"])
    assert response.content == binary()
    partial = client.get(plan["firmware"]["url"], headers={"Range": "bytes=0-23"})
    assert partial.status_code == 206 and partial.content == binary()[:24]
    assert hashlib.sha256(response.content).hexdigest() == plan["firmware"]["sha256"]
    assert upload_firmware(client, "0.9.0", "stable").status_code == 409
    assert event(client, plan, event="boot_success", firmwareVersion="0.9.0", installedAssets=plan["desiredAssets"]).status_code == 409
    assert event(client, plan, event="firmware_confirmed", firmwareVersion="0.9.0").status_code == 200
    assert d.confirmed_firmware == "0.9.0"
    assert event(client, plan, event="boot_success", firmwareVersion="0.9.0", installedAssets=plan["desiredAssets"]).status_code == 200
    assert sync(client, firmware="1.0.0")["firmware"] is None
    client.post(f'/firmware/{plan["firmware"]["id"]}/promote')
    d.firmware_channel = "stable"; db.commit()
    assert sync(client)["firmware"]["version"] == "0.9.0"
    assert client.get("/firmware").status_code == 200


def test_bad_firmware_and_minimum_firmware(client, db):
    device(db)
    assert client.post("/firmware", data={"version": "0.9.0", "channel": "beta"}, files={"file": ("bad.bin", b"bad")}).status_code == 422
    create(client, "game-pong", "game")
    client.post("/assets/game-pong/definition", data={"expected": 1, "definition": '{"minFirmware":"0.9.0"}'})
    d = db.scalar(select(Device)); d.content_selection = ["game-pong"]; db.commit()
    plan = sync(client)
    assert plan["blockedAssets"] == [{"packageId": "game-pong", "minFirmware": "0.9.0"}]
    assert all(p["packageId"] != "game-pong" for p in plan["assetUpdates"])
    assert not sync(client, firmware="0.9.0")["blockedAssets"]


def test_config_change_during_download_and_wrong_device(client, db):
    d = device(db)
    plan = sync(client)
    d.config_version += 1; db.commit()
    assert event(client, plan, event="boot_success", firmwareVersion="0.8.0", installedAssets=plan["desiredAssets"]).status_code == 409
    other = Device(device_id="other", name="Other"); db.add(other); db.commit()
    assert client.post(f'/api/v1/devices/other/sync/{plan["syncId"]}/events', json={"event": "download_started"}).status_code == 404
    d.enabled = False; db.commit()
    assert client.post("/api/v1/devices/leap-test/sync", json={"firmwareVersion": "0.8.0"}).status_code == 404


def test_migrations_fresh_and_existing_preserve_quiz(tmp_path):
    import sqlite3
    import sys
    database = tmp_path / "migration.db"
    env = {**os.environ, "LEAP_DATABASE_URL": f"sqlite:///{database}", "LEAP_DATA_DIR": str(tmp_path)}
    def migrate(*arguments):
        result = subprocess.run([sys.executable, "-m", "alembic", *arguments], env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
    migrate("upgrade", "head")
    migrate("downgrade", "0004")
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO quiz_catalogs (id,name,enabled,created_at) VALUES (1,'Natur',1,'2026-01-01')")
        connection.execute('''INSERT INTO quiz_questions (id,catalog_id,question,answers,explanation,min_age,difficulty,tags)
            VALUES (1,1,'Bleibt erhalten?','["Ja","Nein","Vielleicht","Nie"]','Beispiel',7,1,'["natur"]')''')
    migrate("upgrade", "head")
    migrate("upgrade", "head")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT question,min_age FROM quiz_questions").fetchall() == [("Bleibt erhalten?",7)]
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0005",)
    code = '''from app.core.database import SessionLocal
from app.services.distribution import ensure_packages
from app.models import AssetPackage,QuizQuestion
with SessionLocal() as db:
 ensure_packages(db)
 ensure_packages(db)
 assert db.get(AssetPackage,"quiz-1").current_version == 1
 assert db.get(QuizQuestion,1).question == "Bleibt erhalten?"
'''
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_inventory_and_firmware_reports_survive_new_session(client, db):
    from sqlalchemy.orm import Session
    d = device(db)
    plan = sync(client)
    event(client, plan, event="boot_success", firmwareVersion="0.8.0", installedAssets=plan["desiredAssets"])
    with Session(bind=db.bind) as reopened:
        persisted = reopened.get(Device, d.id)
        assert persisted.installed_assets == plan["desiredAssets"]
        assert persisted.last_sync is not None


def test_numerical_firmware_versions(client, db):
    device(db)
    for version in ["0.10.0", "0.9.9", "0.10.0-beta.2"]:
        assert upload_firmware(client, version, "stable").status_code == 303
    assert sync(client)["firmware"]["version"] == "0.10.0"
