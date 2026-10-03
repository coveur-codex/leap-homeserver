import pytest
from app.models import Device, QuizCatalog, QuizQuestion
from app.services.devices import initialize_pages


def device(db):
    d = Device(device_id="math-child", name="Mathe", age=8)
    initialize_pages(d)
    db.add(d)
    db.commit()
    return d


def test_math_settings_config_preview_and_duplicate(client, db):
    d = device(db)
    assert client.get("/api/v1/devices/math-child/config").json()["mathQuiz"] == {"operation": "add", "limit": 20}
    before = d.config_version
    response = client.post(f"/devices/{d.id}", data={"name": "Mathe", "age": 8, "avatar": "dragon",
        "enabled": "on", "math_settings": "true", "math_operation": "multiply", "math_limit": 10,
        "page_ids": ["home", "quiz"]}, follow_redirects=False)
    assert response.status_code == 303
    config = client.get("/api/v1/devices/math-child/config").json()
    assert config["mathQuiz"] == {"operation": "multiply", "limit": 10}
    assert config["configVersion"] == before + 1
    page = client.get(f"/devices/{d.id}").text
    assert "Katalog auswählen" in page and "Mathe-Quiz" in page and 'value="10"' in page
    assert client.post(f"/devices/{d.id}/duplicate", follow_redirects=False).status_code == 303
    copy = db.query(Device).filter_by(device_id="math-child-copy").one()
    assert copy.math_quiz == d.math_quiz


@pytest.mark.parametrize("operation,limit", [("divide", 20), ("add", 2), ("subtract", 1001), ("multiply", 21)])
def test_invalid_math_settings(client, db, operation, limit):
    d = device(db)
    before = d.config_version
    r = client.post(f"/devices/{d.id}", data={"name": "Mathe", "age": 8, "avatar": "dragon",
        "math_settings": "true", "math_operation": operation, "math_limit": limit})
    assert r.status_code == 422
    db.refresh(d)
    assert d.config_version == before and d.math_quiz == {"operation": "add", "limit": 20}


def test_quiz_catalog_identity_and_age_filter(client, db):
    d = device(db)
    def question(text, age=0):
        return QuizQuestion(question=text, answers=["yes", "no", "maybe", "other"], min_age=age)
    a = QuizCatalog(name="Tiere", questions=[question("Tier"), question("Ältere", 12)])
    b = QuizCatalog(name="Weltraum", questions=[question("Planet")])
    hidden = QuizCatalog(name="Inaktiv", enabled=False, questions=[question("hidden")])
    unassigned = QuizCatalog(name="Nicht zugewiesen", questions=[question("private")])
    d.quiz_catalogs = [a, b, hidden]
    db.add(unassigned)
    db.commit()
    quiz = client.get("/api/v1/devices/math-child/quiz").json()
    assert quiz["catalogs"] == [{"id": a.id, "name": "Tiere"}, {"id": b.id, "name": "Weltraum"}]
    assert {q["q"]: q["catalogId"] for q in quiz["questions"]} == {"Tier": a.id, "Planet": b.id}


def test_math_migration_existing_device(tmp_path):
    import json
    import os
    import sqlite3
    import subprocess
    import sys
    database = tmp_path / "old-device.db"
    env = {**os.environ, "LEAP_DATABASE_URL": f"sqlite:///{database}", "LEAP_DATA_DIR": str(tmp_path)}
    def run(*args):
        result = subprocess.run([sys.executable, *args], env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
    run("-m", "alembic", "upgrade", "0006")
    run("-c", '''from app.core.database import SessionLocal
from app.models import Device
with SessionLocal() as db:
 db.add(Device(device_id="existing", name="Bestehend"))
 db.commit()
''')
    # Initial migration uses today's metadata; reconstruct the pre-0007 schema.
    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE devices DROP COLUMN math_quiz")
    run("-m", "alembic", "upgrade", "head")
    with sqlite3.connect(database) as connection:
        settings, version, name = connection.execute("SELECT math_quiz,config_version,name FROM devices").fetchone()
        assert json.loads(settings) == {"operation": "add", "limit": 20}
        assert version == 2 and name == "Bestehend"
