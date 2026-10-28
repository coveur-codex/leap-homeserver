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
        assert page["enabled"] and page["settings"] == dict(climate=climate, lights=lights, minimum=10, maximum=30)
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
        assert d.config_version == version+1
        assert len([p for p in d.pages if p.page_id == "room"]) == 1
