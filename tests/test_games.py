import io
import json
from zipfile import ZipFile
import pytest
from sqlalchemy import select
from app.models import AssetPackage
from app.services import distribution as service
from test_distribution import create, device, sync


def pet_zip():
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        for name in sorted(service.PET_STATES):
            for frame in range(1, 5):
                archive.writestr(f"Example/data/pet/{name}/frame_{frame:02}.png", b"png")
        for period in ("day", "night"):
            archive.writestr(f"Example/background_{period}/background.png", b"png")
        archive.writestr("Example/idle/notes.txt", b"not a frame")
    return output.getvalue()


def test_games_config_and_pet_sync(client, db):
    d = device(db)
    response = client.get("/api/v1/devices/leap-test/config").json()
    assert {g["id"] for g in response["games"]} == {"tamagotchi", "snake", "hot_potato", "simon_motion", "tilt_maze", "connect_four"}
    create(client, "avatar-pet", "avatar")
    d.avatar = "avatar-pet"
    db.commit()
    assert client.post("/assets/avatar-pet/files", data={"expected": 1}, files={"files": ("pet.zip", pet_zip())}, follow_redirects=False).status_code == 303
    manifest = client.get("/api/v1/packages/avatar-pet/versions/2/manifest").json()
    definition = manifest["definition"]
    pet = definition["tamagotchi"]
    assert set(pet["animations"]) == service.PET_STATES
    for name, animation in pet["animations"].items():
        assert len(animation["frames"]) == 4
        assert animation["frameDurationMs"] == 400
        assert animation["frames"] == sorted(animation["frames"])
    assert definition["animations"]["idle"] == pet["animations"]["idle"]
    assert pet["backgrounds"]["day"] == "Example/background_day/background.png"
    plan = sync(client, firmware="1.0.0-beta.9")
    assert "avatar-pet" in plan["desiredAssets"]
    update = next(u for u in plan["assetUpdates"] if u["packageId"] == "avatar-pet")
    assert update["version"] == 2
    for path in pet["backgrounds"].values():
        file = next(f for f in manifest["files"] if f["path"] == path)
        assert client.get(file["url"]).content == b"png"
    html = client.get(f"/devices/{d.id}").text
    assert 'data-preview-card="SPIELE"' in html and 'data-pet-assets' in html
    assert '/versions/2/files/Example/background_day/background.png' in html


def test_pet_frame_extension_and_delete_are_versioned(client, db):
    create(client, "avatar-pet", "avatar")
    assert client.post("/assets/avatar-pet/files", data={"expected": 1}, files={"files": ("pet.zip", pet_zip())}, follow_redirects=False).status_code == 303
    path = "Example/data/pet/eating/frame_05.png"
    assert client.post("/assets/avatar-pet/files", data={"expected": 2}, files={"files": (path, b"new")}, follow_redirects=False).status_code == 303
    old = client.get("/api/v1/packages/avatar-pet/versions/2/manifest").json()
    latest = client.get("/api/v1/packages/avatar-pet/versions/3/manifest").json()
    assert len(old["definition"]["tamagotchi"]["animations"]["eating"]["frames"]) == 4
    assert len(latest["definition"]["tamagotchi"]["animations"]["eating"]["frames"]) == 5
    assert client.post("/assets/avatar-pet/files/delete", data={"expected": 3, "path": path}, follow_redirects=False).status_code == 303
    background = old["definition"]["tamagotchi"]["backgrounds"]["night"]
    assert client.post("/assets/avatar-pet/files/delete", data={"expected": 4, "path": background}, follow_redirects=False).status_code == 303
    latest = client.get("/api/v1/packages/avatar-pet/versions/5/manifest").json()
    assert len(latest["definition"]["tamagotchi"]["animations"]["eating"]["frames"]) == 4
    assert "night" not in latest["definition"]["tamagotchi"]["backgrounds"]
    assert "night" in old["definition"]["tamagotchi"]["backgrounds"]


@pytest.mark.parametrize("pet", [[], {"animations": []}, {"backgrounds": []},
    {"backgrounds": {"day": "missing.png"}},
    {"animations": {"eating": {"frames": ["missing.png"]}}},
    {"animations": {"idle": {"frames": ["image.svg"]}}}])
def test_invalid_pet_definition_rejected(client, db, pet):
    create(client, "avatar-pet", "avatar")
    assert client.post("/assets/avatar-pet/files", data={"expected": 1}, files={"files": ("image.svg", b"svg")}, follow_redirects=False).status_code == 303
    response = client.post("/assets/avatar-pet/definition", data={"expected": 2, "definition": json.dumps({"tamagotchi": pet})}, follow_redirects=False)
    assert response.status_code == 422
    package = db.scalar(select(AssetPackage).where(AssetPackage.id == "avatar-pet"))
    assert package.current_version == 2


def test_pet_preview_reuses_builtin_avatar_without_new_assets(client, db):
    d = device(db)
    context = service.device_context(db, d)
    idle = context["pet_preview"]["animations"]["idle"]
    assert idle["frames"] and idle["frames"][0].endswith("/preview.png")


def test_existing_pet_upload_is_upgraded_once_and_synced(client, db):
    """Simulate a package written by the server before pet metadata existed."""
    import copy
    from app.models import AssetVersion
    d = device(db)
    create(client, "avatar-old-pet", "avatar")
    d.avatar = "avatar-old-pet"
    db.commit()
    assert client.post("/assets/avatar-old-pet/files", data={"expected": 1}, files={"files": ("old.zip", pet_zip())}, follow_redirects=False).status_code == 303
    version = db.scalar(select(AssetVersion).where(AssetVersion.package_id == "avatar-old-pet", AssetVersion.version == 2))
    old = copy.deepcopy(version.manifest)
    old["definition"].pop("tamagotchi")
    old["definition"]["animations"] = {"idle": {"frames": ["Example/data/pet/idle/frame_01.png"], "frameDurationMs": 1000}}
    info = service.store_bytes(json.dumps(old["definition"], ensure_ascii=False, sort_keys=True).encode())
    next(f for f in old["files"] if f["path"] == "definition.json").update(info)
    version.manifest = old
    db.commit()
    service.ensure_packages(db)
    package = db.get(AssetPackage, "avatar-old-pet")
    assert package.current_version == 3
    new = service.current(db, package).manifest
    assert len(new["definition"]["tamagotchi"]["animations"]["idle"]["frames"]) == 4
    assert set(new["definition"]["tamagotchi"]["backgrounds"]) == {"day", "night"}
    assert new["definition"]["animations"] == old["definition"]["animations"]
    assert service.file_map(service.current(db, package)) == service.file_map(version)
    assert "tamagotchi" not in version.manifest["definition"]
    service.ensure_packages(db)
    assert package.current_version == 3
    plan = sync(client, {"avatar-old-pet": 2}, firmware="1.0.0-beta.11")
    assert next(u for u in plan["assetUpdates"] if u["packageId"] == "avatar-old-pet")["version"] == 3
    definition_file = next(f for f in new["files"] if f["path"] == "definition.json")
    assert client.get(definition_file["url"]).json() == new["definition"]


def test_existing_generic_animation_metadata_can_drive_pet(client, db):
    create(client, "avatar-generic", "avatar")
    assert client.post("/assets/avatar-generic/files", data={"expected": 1}, files=[("files", ("one.png", b"png")), ("files", ("two.png", b"png"))], follow_redirects=False).status_code == 303
    definition = {"animations": {"idle": {"frames": ["two.png", "one.png"], "frameDurationMs": 700},
                                 "happy": {"frames": ["one.png", "two.png"], "frameDurationMs": 600}}}
    assert client.post("/assets/avatar-generic/definition", data={"expected": 2, "definition": json.dumps(definition)}, follow_redirects=False).status_code == 303
    manifest = client.get("/api/v1/packages/avatar-generic/versions/3/manifest").json()
    assert manifest["definition"]["tamagotchi"]["animations"] == definition["animations"]
