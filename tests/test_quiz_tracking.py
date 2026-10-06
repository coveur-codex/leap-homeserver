from importlib import import_module
import json

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, select, text

from app.models import AssetPackage, Device, QuizAttempt, QuizCatalog, QuizQuestion
from app.services.devices import initialize_pages
from app.services.distribution import quiz_data, publish_quiz, current, file_map, blob_path


def device(db, name="child"):
    row = Device(device_id=name, name=name)
    initialize_pages(row)
    db.add(row)
    db.commit()
    return row


def attempt(event="one", kind="math"):
    data = {
        "eventId": event, "kind": kind, "quizSetId": "math" if kind == "math" else "quiz-7",
        "quizSetName": "Mathe-Quiz" if kind == "math" else "Tiere",
        "quizSetVersion": 3, "questionId": None if kind == "math" else 42,
        "questionIndex": 0, "question": "7 + 5 = ?", "answers": ["10", "12", "11", "13"],
        "selectedIndex": 2, "correctIndex": 1, "elapsedMs": 1234,
        "answeredAt": "2026-10-06T12:00:00Z", "firmwareVersion": "1.0.0-beta.20",
    }
    if kind == "math":
        data.update(mathOperation="add", mathLimit=20)
    return data


def test_exact_snapshot_retry_and_web_history(client, db):
    d = device(db)
    data = attempt()
    for _ in range(2):
        response = client.post("/api/v1/devices/child/quiz-attempts", json=data)
        assert response.status_code == 200 and response.json() == {"ok": True, "eventId": "one"}
    rows = db.scalars(select(QuizAttempt)).all()
    assert len(rows) == 1 and not rows[0].correct
    # Later config/catalog edits cannot alter an already recorded task.
    d.math_quiz = {"operation": "multiply", "limit": 10}
    db.commit()
    result = client.get("/api/v1/devices/child/quiz-attempts").json()["attempts"][0]
    assert result["question"] == data["question"] and result["answers"] == data["answers"]
    assert result["selectedIndex"] == 2 and result["correctIndex"] == 1
    assert result["elapsedMs"] == 1234 and result["mathOperation"] == "add"
    assert not result["correct"] and result["receivedAt"]
    page = client.get(f"/devices/{d.id}/quiz-results")
    assert page.status_code == 200
    assert "7 + 5 = ?" in page.text and "1,234 s" in page.text
    assert "11 <strong>← Gewählt" in page.text and "12 <strong>✓ Richtige Antwort" in page.text
    assert "1 beantwortete Aufgaben · 0 richtig" in page.text
    assert f'/devices/{d.id}/quiz-results' in client.get(f"/devices/{d.id}").text
    changed = {**data, "selectedIndex": 1}
    assert client.post("/api/v1/devices/child/quiz-attempts", json=changed).status_code == 409
    assert not db.scalar(select(QuizAttempt)).correct


def test_legacy_package_offline_timestamp_and_device_isolation(client, db):
    d = device(db)
    other = device(db, "other")
    data = attempt(kind="catalog")
    data.update(question="<script>alert('x')</script>", questionId=None, answeredAt=None,
                elapsedMs=None, selectedIndex=1)
    # Existing catalogs allow long answer strings; valid offline events must not block retries.
    data["answers"][0] = "a" * 10001
    assert client.post("/api/v1/devices/child/quiz-attempts", json=data).status_code == 200
    # Dedupe is scoped per device, and an offline event is accepted after reassignment.
    assert client.post("/api/v1/devices/other/quiz-attempts", json=data).status_code == 200
    assert len(client.get("/api/v1/devices/other/quiz-attempts").json()["attempts"]) == 1
    page = client.get(f"/devices/{d.id}/quiz-results").text
    assert "&lt;script&gt;" in page and "<script>alert" not in page
    assert "Geräteuhr noch nicht synchronisiert" in page and "Nicht erfasst" in page
    assert "1 beantwortete Aufgaben · 1 richtig" in page
    other.enabled = False
    db.commit()
    for method in (client.get, client.post):
        args = {"json": data} if method == client.post else {}
        assert method("/api/v1/devices/other/quiz-attempts", **args).status_code == 404
        assert method("/api/v1/devices/missing/quiz-attempts", **args).status_code == 404
    assert client.get("/devices/99999/quiz-results").status_code == 404


@pytest.mark.parametrize("changes", [
    {"selectedIndex": 4}, {"correctIndex": -1}, {"answers": ["only one"]},
    {"elapsedMs": -1}, {"elapsedMs": 4294967296}, {"question": ""},
    {"questionIndex": -1}, {"kind": "unknown"}, {"mathOperation": None},
    {"mathOperation": "multiply", "mathLimit": 21}, {"answeredAt": "2026-10-06T12:00:00"},
    {"questionId": "q" * 121},
])
def test_invalid_snapshot(client, db, changes):
    device(db)
    assert client.post("/api/v1/devices/child/quiz-attempts", json={**attempt(), **changes}).status_code == 422
    assert db.scalar(select(QuizAttempt)) is None


def test_history_pagination(client, db):
    d = device(db)
    for i in range(51):
        data = attempt(str(i))
        assert client.post("/api/v1/devices/child/quiz-attempts", json=data).status_code == 200
    result = client.get("/api/v1/devices/child/quiz-attempts?limit=50").json()
    assert len(result["attempts"]) == 50 and result["hasMore"]
    assert result["attempts"][0]["eventId"] == "50"
    result = client.get("/api/v1/devices/child/quiz-attempts?offset=50").json()
    assert len(result["attempts"]) == 1 and not result["hasMore"]
    assert '?offset=50' in client.get(f"/devices/{d.id}/quiz-results").text
    assert '?offset=0' in client.get(f"/devices/{d.id}/quiz-results?offset=50").text


def test_published_questions_keep_ids(db):
    catalog = QuizCatalog(name="Tiere", questions=[QuizQuestion(question="Tier?", answers=["a", "b", "c", "d"])])
    db.add(catalog)
    db.commit()
    rows = quiz_data(catalog)
    assert rows[0]["id"] == catalog.questions[0].id and rows[0]["catalogId"] == catalog.id
    package = AssetPackage(id="quiz-test", kind="quiz", name="Tiere", catalog_id=catalog.id, current_version=0)
    db.add(package)
    # The question editor appends new rows without flushing them first.
    new = QuizQuestion(question="Neu?", answers=["1", "2", "3", "4"])
    catalog.questions.append(new)
    publish_quiz(db, package, catalog, 0)
    db.commit()
    info = file_map(current(db, package))["questions.json"]
    published = json.loads(blob_path(info["sha256"]).read_text())["questions"]
    assert published[-1]["id"] == new.id and new.id is not None
    assert published[-1]["catalogId"] == catalog.id


def test_tracking_migration_preserves_data(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    migration = import_module("migrations.versions.0009_quiz_tracking")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE devices (id INTEGER PRIMARY KEY, name TEXT)"))
        connection.execute(text("INSERT INTO devices VALUES (1, 'Existing')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()
        assert "quiz_attempts" in inspect(connection).get_table_names()
        assert connection.execute(text("SELECT name FROM devices")).scalar() == "Existing"
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert "quiz_attempts" not in inspect(connection).get_table_names()
        assert connection.execute(text("SELECT name FROM devices")).scalar() == "Existing"
