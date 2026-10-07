from sqlalchemy import select

from app.models import AssetVersion, FirmwareRelease, SyncRun
from app.services import distribution as service
from test_distribution import binary, create, device, event, sync, upload_firmware


def test_withdraw_restore_and_existing_plan(client, db):
    d = device(db)
    upload_firmware(client, "0.8.5", "stable")
    upload_firmware(client, "0.9.0", "stable")
    plan = sync(client)
    release_id = plan["firmware"]["id"]
    url = plan["firmware"]["url"]
    assert client.get(url).headers["cache-control"] == "no-store"
    assert client.post(f"/firmware/{release_id}/withdraw", follow_redirects=False).status_code == 303
    assert client.get(url).status_code == 404
    assert service.blob_path(plan["firmware"]["sha256"]).is_file()
    # Already installed firmware may still be reported against the old plan.
    assert event(client, plan, event="firmware_confirmed", firmwareVersion="0.9.0").status_code == 200
    assert d.confirmed_firmware == "0.9.0"
    assert sync(client)["firmware"]["version"] == "0.8.5"
    d.firmware_channel = "beta"; db.commit()
    assert sync(client)["firmware"]["version"] == "0.8.5"
    assert sync(client, firmware="0.9.0")["firmware"] is None
    page = client.get("/firmware").text
    assert "Zurückgezogen" in page and f'/firmware/{release_id}/restore' in page
    assert url not in page
    assert client.post(f"/firmware/{release_id}/promote").status_code == 409
    assert client.post(f"/firmware/{release_id}/restore", follow_redirects=False).status_code == 303
    assert client.get(url).content == binary()
    assert sync(client)["firmware"]["version"] == "0.9.0"


def test_delete_preserves_reports_and_reserves_version(client, db):
    d = device(db)
    upload_firmware(client, "0.9.0", "stable")
    plan = sync(client)
    release_id = plan["firmware"]["id"]
    path = service.blob_path(plan["firmware"]["sha256"])
    assert event(client, plan, event="firmware_confirmed", firmwareVersion="0.9.0").status_code == 200
    assert client.post(f"/firmware/{release_id}/delete").status_code == 422
    assert path.is_file() and client.get(plan["firmware"]["url"]).status_code == 200
    assert client.post(f"/firmware/{release_id}/delete", data={"confirm": "true"}, follow_redirects=False).status_code == 303
    assert not path.exists()
    assert client.get(plan["firmware"]["url"]).status_code == 404
    assert d.firmware_version == d.confirmed_firmware == "0.9.0"
    assert db.get(SyncRun, plan["syncId"]).plan["firmware"]["id"] == release_id
    assert f'/firmware/{release_id}/delete' not in client.get("/firmware").text
    assert sync(client)["firmware"] is None
    assert upload_firmware(client, "0.9.0", "stable").status_code == 409
    for action in ("promote", "restore", "withdraw", "delete"):
        assert client.post(f"/firmware/{release_id}/{action}", data={"confirm": "true"}).status_code == 404
        assert client.post(f"/firmware/9999/{action}", data={"confirm": "true"}).status_code == 404


def test_delete_keeps_shared_release_binary(client, db):
    upload_firmware(client, "0.8.5", "beta")
    upload_firmware(client, "0.9.0", "stable")
    releases = db.scalars(select(FirmwareRelease).order_by(FirmwareRelease.id)).all()
    path = service.blob_path(releases[0].sha256)
    assert releases[0].sha256 == releases[1].sha256
    client.post(f"/firmware/{releases[0].id}/withdraw")
    client.post(f"/firmware/{releases[1].id}/delete", data={"confirm": "true"})
    assert path.is_file()
    client.post(f"/firmware/{releases[0].id}/restore")
    assert client.get(f"/api/v1/firmware/{releases[0].id}/binary").content == binary()
    client.post(f"/firmware/{releases[0].id}/delete", data={"confirm": "true"})
    assert not path.exists()


def test_delete_keeps_historical_asset_binary(client, db):
    upload_firmware(client, "0.9.0", "beta")
    release = db.scalar(select(FirmwareRelease))
    create(client, "common-backup", "common")
    client.post("/assets/common-backup/files", data={"expected": 1}, files={"files": ("backup.bin", binary())})
    row = db.scalar(select(AssetVersion).where(AssetVersion.package_id == "common-backup", AssetVersion.version == 2))
    url = next(item["url"] for item in row.manifest["files"] if item["path"] == "backup.bin")
    client.post("/assets/common-backup/files/delete", data={"expected": 2, "path": "backup.bin"})
    client.post(f"/firmware/{release.id}/delete", data={"confirm": "true"})
    assert service.blob_path(release.sha256).is_file()
    assert client.get(url).content == binary()


def test_restore_requires_binary(client, db):
    upload_firmware(client, "0.9.0", "beta")
    release = db.scalar(select(FirmwareRelease))
    client.post(f"/firmware/{release.id}/withdraw")
    service.blob_path(release.sha256).unlink()
    assert client.post(f"/firmware/{release.id}/restore").status_code == 409
    assert release.withdrawn


def test_migration_preserves_existing_firmware(tmp_path):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from importlib import import_module
    from sqlalchemy import create_engine, text

    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE firmware_releases (id INTEGER PRIMARY KEY, version TEXT, channel TEXT, sha256 TEXT)"))
        connection.execute(text("INSERT INTO firmware_releases VALUES (7, '0.9.0', 'stable', 'original-hash')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration = import_module('migrations.versions.0011_firmware_withdrawal')
            migration.upgrade()
            migration.upgrade()
        assert connection.execute(text("SELECT id, version, channel, sha256, withdrawn, deleted FROM firmware_releases")).all() == [
            (7, '0.9.0', 'stable', 'original-hash', 0, 0)]
