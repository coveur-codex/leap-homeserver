from app.models import QuizCatalog, QuizQuestion
from test_app import make_device


def test_large_quiz_metadata_and_sample_leave_package_complete(client, db):
    device = make_device(db, 8)
    first = QuizCatalog(name="Großer Katalog")
    first.questions = [QuizQuestion(question=f"Frage {i} " + "x" * 1100,
        answers=["a", "b", "c", "d"], min_age=7) for i in range(300)]
    second = QuizCatalog(name="Kleiner Katalog")
    second.questions = [QuizQuestion(question="Für Kinder", answers=["a", "b", "c", "d"], min_age=7),
                        QuizQuestion(question="Zu alt", answers=["a", "b", "c", "d"], min_age=12)]
    device.quiz_catalogs.extend([first, second])
    db.commit()
    path = f"/api/v1/devices/{device.device_id}/quiz"
    full = client.get(path)
    assert len(full.content) > 256 * 1024
    assert len(full.json()["questions"]) == 301
    metadata = client.get(path, params={"metadataOnly": "true"}).json()
    assert metadata["questions"] == []
    assert {c["id"] for c in metadata["catalogs"]} == {first.id, second.id}
    sampled = client.get(path, params={"limitPerCatalog": 200})
    assert len(sampled.content) < 256 * 1024
    questions = sampled.json()["questions"]
    assert sum(q["catalogId"] == first.id for q in questions) == 200
    assert sum(q["catalogId"] == second.id for q in questions) == 1
    assert len({q["id"] for q in questions}) == 201
    assert all(q["minAge"] <= 8 for q in questions)
    assert client.get(path, params={"limitPerCatalog": 201}).status_code == 422
    # Sampling the legacy endpoint must never truncate the versioned catalog.
    plan = client.post(f"/api/v1/devices/{device.device_id}/sync", json={
        "firmwareVersion": "1.0.0-beta.16", "installedAssets": {}}).json()
    update = next(u for u in plan["assetUpdates"] if u["packageId"] == f"quiz-{first.id}")
    manifest = client.get(update["manifestUrl"]).json()
    questions_file = next(f for f in manifest["files"] if f["path"] == manifest["definition"]["questionsFile"])
    catalog = client.get(questions_file["url"])
    assert len(catalog.content) > 256 * 1024
    assert len(catalog.json()["questions"]) == 300
