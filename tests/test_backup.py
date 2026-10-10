import sqlite3
from contextlib import closing
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base, get_db
from app.main import app
from app.models import Device
from app.web import routes


def track_snapshots(monkeypatch):
    snapshots = []
    original = routes.backup_database

    def backup(engine, destination):
        snapshots.append(destination)
        original(engine, destination)

    monkeypatch.setattr(routes, "backup_database", backup)
    return snapshots


def test_database_download_is_complete_and_cleans_up(client, db, tmp_path, monkeypatch):
    db.add(Device(device_id="backup-device", name="Backup-Gerät"))
    db.commit()
    snapshots = track_snapshots(monkeypatch)
    page = client.get("/system")
    assert 'action="/system/database/backup"' in page.text
    assert "SQLite-Datenbank herunterladen" in page.text

    response = client.get("/system/database/backup")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.sqlite3"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"].startswith('attachment; filename="leap-backup-')
    assert response.headers["content-disposition"].endswith('-UTC.db"')
    assert response.content.startswith(b"SQLite format 3\x00")
    assert int(response.headers["content-length"]) == len(response.content)
    downloaded = tmp_path / "download.db"
    downloaded.write_bytes(response.content)
    with closing(sqlite3.connect(downloaded)) as backup:
        assert backup.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        tables = {row[0] for row in backup.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert tables - {"sqlite_sequence"} == set(Base.metadata.tables)
        assert backup.execute("SELECT name FROM sqlite_sequence").fetchall() == []
        assert backup.execute("SELECT name FROM devices WHERE device_id='backup-device'").fetchone() == ("Backup-Gerät",)
    assert len(snapshots) == 1
    assert not snapshots[0].parent.exists()
    assert db.query(Device).filter_by(device_id="backup-device").one().name == "Backup-Gerät"


def test_download_includes_wal_and_migration_metadata(client, tmp_path, monkeypatch):
    database = tmp_path / "live.db"
    engine = create_engine(f"sqlite:///{database}", connect_args={"check_same_thread": False})
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA journal_mode=WAL").scalar() == "wal"
            connection.exec_driver_sql("PRAGMA wal_autocheckpoint=0")
            connection.commit()
            Base.metadata.create_all(connection)
            connection.exec_driver_sql("CREATE TABLE alembic_version (version_num TEXT PRIMARY KEY)")
            connection.exec_driver_sql("INSERT INTO alembic_version VALUES ('backup-test')")
            connection.commit()
            with Session(engine) as session:
                session.add(Device(device_id="wal-device", name="WAL-Gerät"))
                session.commit()
            assert Path(f"{database}-wal").stat().st_size > 0

            def database_session():
                with Session(engine) as session:
                    yield session

            monkeypatch.setitem(app.dependency_overrides, get_db, database_session)
            response = client.get("/system/database/backup")
            assert response.status_code == 200
            downloaded = tmp_path / "wal-download.db"
            downloaded.write_bytes(response.content)
            with closing(sqlite3.connect(downloaded)) as backup:
                assert backup.execute("PRAGMA integrity_check").fetchone() == ("ok",)
                assert backup.execute("SELECT name FROM devices WHERE device_id='wal-device'").fetchone() == ("WAL-Gerät",)
                assert backup.execute("SELECT version_num FROM alembic_version").fetchone() == ("backup-test",)
    finally:
        engine.dispose()


def test_failed_backup_cleans_up_and_reports_error(client, monkeypatch):
    snapshots = []

    def fail(engine, destination):
        snapshots.append(destination)
        destination.write_bytes(b"partial backup")
        raise sqlite3.OperationalError("internal database path")

    monkeypatch.setattr(routes, "backup_database", fail)
    response = client.get("/system/database/backup")
    assert response.status_code == 500
    assert response.json()["detail"] == "Das Datenbank-Backup konnte nicht erstellt werden."
    assert len(snapshots) == 1
    assert not snapshots[0].parent.exists()


def test_non_sqlite_database_has_no_download(client, db, monkeypatch):
    monkeypatch.setattr(db.get_bind().dialect, "name", "postgresql")
    page = client.get("/system")
    assert page.status_code == 200
    assert 'action="/system/database/backup"' not in page.text
    assert "Der Datenbank-Download ist nur für SQLite verfügbar." in page.text
    assert client.get("/system/database/backup").status_code == 503
