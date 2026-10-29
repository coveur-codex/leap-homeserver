import asyncio
import json
from copy import deepcopy

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.models import Device
from app.services import room
from app.services.devices import initialize_pages


@pytest.fixture
def ha(monkeypatch):
    states = {
        "climate.heizung_lars_erik": {"state": "heat", "attributes": {"temperature": 20, "current_temperature": 19.5, "min_temp": 5, "max_temp": 30}},
        "light.einfahrt_garage": {"state": "off", "attributes": {"supported_color_modes": ["rgb"]}},
        "light.erik_tisch": {"state": "off", "attributes": {"supported_color_modes": ["brightness"]}},
        "light.lars_hochbett": {"state": "off", "attributes": {"supported_color_modes": ["xy"]}},
        "scene.anna_lichterkette_szene": {"state": "unknown", "attributes": {"friendly_name": "Annas Szene"}},
        "light.lars_tisch": {"state": "off", "attributes": {"supported_color_modes": ["hs"]}},
    }
    calls, options = [], {"confirm": True, "fail": False, "unit": "°C"}
    real_client = httpx.AsyncClient
    async def handle(request):
        assert request.headers["authorization"] == "Bearer test-secret"
        if options["fail"]: raise httpx.ConnectError("private upstream details", request=request)
        path = request.url.path
        if path == "/api/config": return httpx.Response(200, json={"unit_system": {"temperature": options["unit"]}})
        if path.startswith("/api/states/"):
            entity = path.removeprefix("/api/states/")
            return httpx.Response(200 if entity in states else 404, json=deepcopy(states.get(entity, {})))
        data = json.loads(request.content)
        calls.append((path, data))
        entity = data["entity_id"]
        await asyncio.sleep(.001)
        if path == "/api/services/scene/turn_on": return httpx.Response(200, json=[])
        if options["confirm"]:
            if "temperature" in data: states[entity]["attributes"]["temperature"] = data["temperature"]
            else: states[entity]["state"] = "off" if path.endswith("turn_off") else "on"
        return httpx.Response(200, json=[])
    monkeypatch.setattr(room.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw))
    monkeypatch.setattr(settings, "home_assistant_token", SecretStr("test-secret"))
    room._pending.clear()
    room._locks.clear()
    return states, calls, options


def device(db, did="leap-erik"):
    d = Device(device_id=did, name=did)
    initialize_pages(d)
    db.add(d)
    db.commit()
    return d


def test_mapping_and_secret(client, db, ha):
    for name, (climate, lights) in room.DEFAULT_ROOMS.items():
        device(db, name)
        config = client.get(f"/api/v1/devices/{name}/config").json()
        page = next(p for p in config["pages"] if p["id"] == "room")
        assert page["enabled"] and page["settings"] == room.default_config(name)
        assert "test-secret" not in json.dumps(config)
    data = client.get("/api/v1/devices/leap-erik/room").json()
    assert data["climate"]["target"] == 20 and data["climate"]["controllable"]
    assert data["lights"][0]["colorSupported"] and not data["lights"][1]["colorSupported"]


def test_steps_limits_and_colors(client, db, ha):
    states, calls, _ = ha
    device(db)
    path = "/api/v1/devices/leap-erik/room"
    for action, expected in [("warmer", 21), ("colder", 20)]:
        r = client.post(path, json={"target": "climate", "action": action})
        assert r.status_code == 200 and r.json()["climate"]["target"] == expected
    for target, action in [(30, "warmer"), (10, "colder")]:
        states["climate.heizung_lars_erik"]["attributes"]["temperature"] = target
        assert client.post(path, json={"target": "climate", "action": action}).status_code == 409
    states["climate.heizung_lars_erik"]["attributes"].update(temperature=27, max_temp=27)
    assert client.post(path, json={"target": "climate", "action": "warmer"}).status_code == 409
    assert len(calls) == 2
    assert client.post(path, json={"target": "light0", "action": "color", "color": "lila"}).status_code == 200
    assert calls[-1][1]["rgb_color"] == [180, 0, 255]
    assert client.post(path, json={"target": "light1", "action": "color", "color": "rot"}).status_code == 409
    assert client.post(path, json={"target": "light0", "action": "off"}).status_code == 200
    assert calls[-1][0].endswith("turn_off")


def test_reject_unassigned_disabled_and_invalid(client, db, ha):
    d = device(db, "leap-papa")
    path = "/api/v1/devices/leap-papa/room"
    assert client.post(path, json={"target": "light0", "action": "on"}).status_code == 403
    for body in [{"target": "climate", "action": "on"}, {"target": "light0", "action": "color"},
                 {"target": "climate", "action": "warmer", "entity_id": "climate.other"}]:
        assert client.post(path, json=body).status_code == 422
    page = next(p for p in d.pages if p.page_id == "room")
    page.enabled = False
    db.commit()
    assert client.get(path).status_code == 403
    d.enabled = False
    db.commit()
    assert client.get(path).status_code == 404
    assert not ha[1]


def test_editor(client, db):
    d = device(db)
    assert client.get(f"/devices/{d.id}").status_code == 200
    response = client.post(f"/devices/{d.id}/room", data={"enabled": "true", "climate": "climate.test", "light0": "light.test", "minimum": 10, "maximum": 30}, follow_redirects=False)
    assert response.status_code == 303
    cfg = client.get("/api/v1/devices/leap-erik/config").json()
    assert next(p for p in cfg["pages"] if p["id"] == "room")["settings"]["climate"] == "climate.test"
    for data in [{"climate": "light.invalid"}, {"minimum": 9}, {"minimum": 30, "maximum": 10}]:
        assert client.post(f"/devices/{d.id}/room", data=data).status_code == 422


@pytest.mark.asyncio
async def test_shared_thermostat_serialized(db, ha):
    erik, lars = device(db), device(db, "leap-lars")
    cmd = room.Command(target="climate", action="warmer")
    await asyncio.gather(room.command(erik, cmd), room.command(lars, cmd))
    assert [c[1]["temperature"] for c in ha[1]] == [21, 22]
    assert (await room.read_room(erik))["climate"]["target"] == 22
    assert (await room.read_room(lars))["climate"]["target"] == 22


def test_confirmation_timeout_and_failures(client, db, ha, monkeypatch):
    states, calls, options = ha
    device(db)
    path = "/api/v1/devices/leap-erik/room"
    options["confirm"] = False
    assert "bestätigung" in client.post(path, json={"target": "climate", "action": "warmer"}).json()["notice"]
    assert client.post(path, json={"target": "climate", "action": "warmer"}).status_code == 409
    assert len(calls) == 1
    target, sent = room._pending["climate.heizung_lars_erik"]
    room._pending["climate.heizung_lars_erik"] = (target, sent-16)
    assert client.post(path, json={"target": "climate", "action": "colder"}).status_code == 200
    options["fail"] = True
    response = client.get(path)
    assert response.status_code == 503 and "private upstream" not in response.text
    monkeypatch.setattr(settings, "home_assistant_token", SecretStr(""))
    assert client.get(path).status_code == 503


def test_missing_entities_unavailable_and_non_celsius(client, db, ha):
    states, calls, options = ha
    device(db)
    path = "/api/v1/devices/leap-erik/room"
    del states["light.einfahrt_garage"]
    assert not client.get(path).json()["lights"][0]["available"]
    states["climate.heizung_lars_erik"]["state"] = "unavailable"
    assert client.post(path, json={"target": "climate", "action": "warmer"}).status_code == 409
    states["climate.heizung_lars_erik"]["state"] = "heat"
    options["unit"] = "°F"
    assert client.post(path, json={"target": "climate", "action": "warmer"}).status_code == 409
    assert not calls


def test_migration_preserves_existing_device_pages(tmp_path):
    import os
    import subprocess
    import sys
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    url = f"sqlite:///{tmp_path / 'room-migration.db'}"
    env = {**os.environ, "LEAP_DATABASE_URL": url, "LEAP_DATA_DIR": str(tmp_path)}
    def migrate(revision):
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", revision],
                       env=env, capture_output=True, check=True, timeout=30)
    migrate("0021")
    engine = create_engine(url)
    with Session(engine) as session:
        d = Device(device_id="leap-erik", name="Erik")
        initialize_pages(d)
        d.pages = [p for p in d.pages if p.page_id != "room"]
        d.pages[0].settings = {"custom": "keep"}
        session.add(d)
        session.commit()
        before = [(p.page_id, p.position, p.settings) for p in d.pages]
        version = d.config_version
    migrate("head")
    migrate("head")
    with Session(engine) as session:
        d = session.scalar(select(Device))
        assert [(p.page_id, p.position, p.settings) for p in d.pages if p.page_id != "room"] == before
        page = next(p for p in d.pages if p.page_id == "room")
        assert page.enabled and page.settings == room.default_config("leap-erik")
        assert d.config_version == version+2
        assert len([p for p in d.pages if p.page_id == "room"]) == 1


def test_absolute_temperature_is_single_write_and_validated(client, db, ha):
    states, calls, options = ha
    device(db)
    path = "/api/v1/devices/leap-erik/room"
    response = client.post(path, json={"target": "climate", "action": "set_temperature", "temperature": 24})
    assert response.status_code == 200 and response.json()["climate"]["target"] == 24
    assert response.json()["temperatureSetSupported"]
    assert len(calls) == 1 and calls[0][1] == {"entity_id": "climate.heizung_lars_erik", "temperature": 24}
    for value in (10, 30, 20.5):
        assert client.post(path, json={"target": "climate", "action": "set_temperature", "temperature": value}).status_code == 200
    for value in (9, 31, "NaN", "Infinity"):
        assert client.post(path, json={"target": "climate", "action": "set_temperature", "temperature": value}).status_code == 422
    before = len(calls)
    states["climate.heizung_lars_erik"]["attributes"]["max_temp"] = 25
    assert client.post(path, json={"target": "climate", "action": "set_temperature", "temperature": 26}).status_code == 409
    for body in [dict(target="climate", action="set_temperature"),
                 dict(target="climate", action="warmer", temperature=23),
                 dict(target="light0", action="set_temperature", temperature=23),
                 dict(target="light0", action="on", temperature=23)]:
        assert client.post(path, json=body).status_code == 422
    assert len(calls) == before


def test_absolute_replaces_unconfirmed_target_and_shared_state(client, db, ha):
    states, calls, options = ha
    device(db)
    device(db, "leap-lars")
    options["confirm"] = False
    erik = "/api/v1/devices/leap-erik/room"
    lars = "/api/v1/devices/leap-lars/room"
    assert client.post(erik, json={"target": "climate", "action": "set_temperature", "temperature": 24}).status_code == 200
    assert client.post(lars, json={"target": "climate", "action": "set_temperature", "temperature": 20}).status_code == 200
    assert [c[1]["temperature"] for c in calls] == [24, 20]
    options["confirm"] = True
    assert client.post(erik, json={"target": "climate", "action": "set_temperature", "temperature": 23}).status_code == 200
    assert client.get(lars).json()["climate"]["target"] == 23


def test_ten_colors_and_current_palette_color(client, db, ha):
    states, calls, _ = ha
    device(db)
    path = "/api/v1/devices/leap-erik/room"
    assert len(client.get(path).json()["colors"]) == 10
    for color in ("orange", "rosa", "tuerkis", "hellblau"):
        assert client.post(path, json={"target": "light0", "action": "color", "color": color}).status_code == 200
        assert calls[-1][1]["rgb_color"] == room.COLORS[color]
        attrs = states["light.einfahrt_garage"]["attributes"]
        attrs["rgb_color"] = room.COLORS[color]
        assert client.get(path).json()["lights"][0]["color"] == color
        attrs["rgb_color"] = [value/2 for value in room.COLORS[color]]
        assert client.get(path).json()["lights"][0]["color"] == color
    states["light.einfahrt_garage"]["state"] = "off"
    assert client.get(path).json()["lights"][0]["color"] == "aus"
    states["light.einfahrt_garage"]["state"] = "on"
    for invalid in (None, [1], ["red", 1, 1], [0, 0, 0]):
        states["light.einfahrt_garage"]["attributes"]["rgb_color"] = invalid
        assert client.get(path).json()["lights"][0]["color"] is None


def assign_scene(db, d, light="light.einfahrt_garage", scene="scene.anna_lichterkette_szene"):
    page = next(p for p in d.pages if p.page_id == "room")
    page.settings = {**page.settings, "light_scenes": {light: scene}}
    db.commit()


def test_scene_is_assigned_per_light_and_triggered_as_scene(client, db, ha):
    states, calls, _ = ha
    d = device(db)
    assign_scene(db, d)
    path = "/api/v1/devices/leap-erik/room"
    lights = client.get(path).json()["lights"]
    assert lights[0]["sceneSupported"] and not lights[1]["sceneSupported"]
    response = client.post(path, json={"target": "light0", "action": "scene"})
    assert response.status_code == 200 and response.json()["notice"] == "Szene gesendet"
    assert calls == [("/api/services/scene/turn_on", {"entity_id": "scene.anna_lichterkette_szene"})]
    assert not response.json()["lights"][0]["on"]  # A scene invocation does not invent lamp/mode confirmation.
    assert client.post(path, json={"target": "light1", "action": "scene"}).status_code == 403
    assert len(calls) == 1
    assert client.post(path, json={"target": "light0", "action": "off"}).status_code == 200
    assert calls[-1] == ("/api/services/light/turn_off", {"entity_id": "light.einfahrt_garage"})


def test_scene_does_not_require_rgb_support_and_errors_do_not_send(client, db, ha):
    states, calls, _ = ha
    d = device(db)
    assign_scene(db, d, light="light.erik_tisch")
    path = "/api/v1/devices/leap-erik/room"
    light = client.get(path).json()["lights"][1]
    assert light["sceneSupported"] and not light["colorSupported"]
    assert client.post(path, json={"target": "light1", "action": "scene"}).status_code == 200
    for invalid in [dict(target="climate", action="scene"),
                    dict(target="light1", action="scene", color="rot"),
                    dict(target="light1", action="scene", temperature=23),
                    dict(target="light1", action="scene", entity_id="scene.other")]:
        assert client.post(path, json=invalid).status_code == 422
    before = len(calls)
    states["scene.anna_lichterkette_szene"]["state"] = "unavailable"
    assert client.post(path, json={"target": "light1", "action": "scene"}).status_code == 409
    del states["scene.anna_lichterkette_szene"]
    assert client.post(path, json={"target": "light1", "action": "scene"}).status_code == 503
    assert len(calls) == before


def test_scene_editor_validation_preservation_reorder_and_clear(client, db):
    d = device(db)
    path = f"/devices/{d.id}/room"
    data = dict(enabled="true", light0="light.einfahrt_garage", light1="light.erik_tisch",
                scene0="scene.anna_lichterkette_szene", minimum=10, maximum=30)
    assert client.post(path, data=data, follow_redirects=False).status_code == 303
    page = next(p for p in d.pages if p.page_id == "room")
    expected = {"light.einfahrt_garage": "scene.anna_lichterkette_szene"}
    assert page.settings["light_scenes"] == expected
    html = client.get(f"/devices/{d.id}").text
    assert 'name="scene0"' in html and 'value="scene.anna_lichterkette_szene"' in html
    # Old form clients omit the field; assignments remain bound to entity IDs, not positions.
    data.pop("scene0")
    data.update(light0="light.erik_tisch", light1="light.einfahrt_garage")
    assert client.post(path, data=data, follow_redirects=False).status_code == 303
    assert page.settings["light_scenes"] == expected
    for invalid in [dict(data, scene0="light.invalid"), dict(data, scene1="scene.bad/path"),
                    dict(data, light0="", scene0="scene.test")]:
        assert client.post(path, data=invalid).status_code == 422
    # Empty input explicitly removes the association.
    data["scene1"] = ""
    assert client.post(path, data=data, follow_redirects=False).status_code == 303
    assert page.settings["light_scenes"] == {}
    with pytest.raises(ValueError):
        room.RoomConfig(lights=["light.test"], light_scenes={"light.other": "scene.test"})
    with pytest.raises(ValueError):
        room.RoomConfig(lights=["light.test"], light_scenes={"light.test": "script.test"})


@pytest.mark.parametrize("preset,light,expected", [
    ({}, "light.lichterkette_anna", {"light.lichterkette_anna": "scene.anna_lichterkette_szene"}),
    ({"light.lichterkette_anna": "scene.custom"}, "light.lichterkette_anna", {"light.lichterkette_anna": "scene.custom"}),
    ({}, "light.replacement", {}),
])
def test_scene_migration_preserves_assignments(tmp_path, preset, light, expected):
    import os
    import subprocess
    import sys
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    url = f"sqlite:///{tmp_path / 'scene-migration.db'}"
    env = {**os.environ, "LEAP_DATABASE_URL": url, "LEAP_DATA_DIR": str(tmp_path)}
    def migrate(action, revision):
        subprocess.run([sys.executable, "-m", "alembic", action, revision], env=env,
                       capture_output=True, check=True, timeout=30)
    migrate("upgrade", "0022")
    engine = create_engine(url)
    with Session(engine) as session:
        d = Device(device_id="leap-anna", name="Anna")
        initialize_pages(d)
        page = next(p for p in d.pages if p.page_id == "room")
        settings = {"climate": "climate.custom", "lights": [light], "minimum": 12, "maximum": 25, "custom": "preserve"}
        if preset: settings["light_scenes"] = preset
        page.settings = settings
        page.enabled = False
        session.add(d)
        session.commit()
        before = [(p.page_id, p.position, p.enabled) for p in d.pages]
        version = d.config_version
    migrate("upgrade", "head")
    migrate("upgrade", "head")
    with Session(engine) as session:
        d = session.scalar(select(Device))
        page = next(p for p in d.pages if p.page_id == "room")
        assert page.settings == {**settings, "light_scenes": expected}
        assert [(p.page_id, p.position, p.enabled) for p in d.pages] == before
        assert d.config_version == version + (0 if preset else 1)
    migrate("downgrade", "0022")
    with Session(engine) as session:
        d = session.scalar(select(Device))
        assert "light_scenes" not in next(p for p in d.pages if p.page_id == "room").settings
