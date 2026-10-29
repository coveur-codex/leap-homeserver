"""Small, explicitly assigned Home Assistant surface for LEAP devices."""
import asyncio
import math
import time
from collections import defaultdict
from typing import Literal
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import settings

DEFAULT_ROOMS = {
    "leap-papa": ("climate.heizung_homeoffice", []),
    "leap-erik": ("climate.heizung_lars_erik", ["light.einfahrt_garage", "light.erik_tisch"]),
    "leap-lars": ("climate.heizung_lars_erik", ["light.lars_hochbett", "light.lars_tisch"]),
    "leap-anna": ("climate.trv_z01_80_7", ["light.lichterkette_anna"]),
}
COLORS = {"weiss": [255, 235, 200], "rot": [255, 0, 0], "gruen": [0, 255, 0],
          "blau": [0, 0, 255], "lila": [180, 0, 255], "gelb": [255, 200, 0],
          "orange": [255, 100, 0], "rosa": [255, 80, 160],
          "tuerkis": [0, 255, 200], "hellblau": [80, 180, 255]}
COLOR_MODES = {"hs", "xy", "rgb", "rgbw", "rgbww"}
# One server worker: shared thermostats are serialized across device IDs.
_locks = defaultdict(asyncio.Lock)
_pending = {}


class RoomConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    climate: str = Field("", pattern=r"^(?:climate\.[a-z0-9_]+)?$")
    lights: list[str] = Field(default_factory=list, max_length=2)
    light_scenes: dict[str, str] = Field(default_factory=dict, max_length=2)
    minimum: int = Field(10, ge=10, le=30)
    maximum: int = Field(30, ge=10, le=30)

    @model_validator(mode="after")
    def valid(self):
        import re
        if self.minimum > self.maximum:
            raise ValueError("Temperaturgrenzen sind vertauscht")
        if any(not re.fullmatch(r"light\.[a-z0-9_]+", x) for x in self.lights):
            raise ValueError("Ungültige Lampen-Entity-ID")
        if any(light not in self.lights or not re.fullmatch(r"scene\.[a-z0-9_]+", scene)
               for light, scene in self.light_scenes.items()):
            raise ValueError("Szene muss einer zugeordneten Lampe gehören und eine scene.…-Entity sein")
        if len(set(self.lights)) != len(self.lights):
            raise ValueError("Lampen dürfen nicht doppelt zugeordnet sein")
        return self


def default_config(device_id):
    climate, lights = DEFAULT_ROOMS.get(device_id, ("", []))
    scenes = {"light.lichterkette_anna": "scene.anna_lichterkette_szene"} if device_id == "leap-anna" else {}
    return RoomConfig(climate=climate, lights=lights, light_scenes=scenes).model_dump()


def configuration(device):
    page = next((p for p in device.pages if p.page_id == "room"), None)
    if not page or not page.enabled:
        raise HTTPException(403, "Mein Zimmer ist nicht aktiviert")
    try:
        return RoomConfig.model_validate(page.settings)
    except ValueError:
        raise HTTPException(422, "Zimmerzuordnung ist ungültig") from None


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: Literal["climate", "light0", "light1"]
    action: Literal["warmer", "colder", "set_temperature", "on", "off", "color", "scene"]
    color: Literal["weiss", "rot", "gruen", "blau", "lila", "gelb", "orange", "rosa", "tuerkis", "hellblau"] | None = None

    temperature: float | None = Field(None, ge=10, le=30, allow_inf_nan=False)

    @model_validator(mode="after")
    def valid(self):
        if self.target == "climate":
            if self.action not in {"warmer", "colder", "set_temperature"} or self.color is not None:
                raise ValueError("Ungültiger Heizungsbefehl")
            if (self.action == "set_temperature") != (self.temperature is not None):
                raise ValueError("Zieltemperatur ist nur für set_temperature erforderlich")
        elif self.action not in {"on", "off", "color", "scene"} or (self.action == "color") != (self.color is not None) or self.temperature is not None:
            raise ValueError("Ungültiger Lichtbefehl")
        return self


def number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


class HomeAssistant:
    async def __aenter__(self):
        url = settings.home_assistant_url.rstrip("/")
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise HTTPException(503, "Home-Assistant-Adresse ist ungültig")
        token = settings.home_assistant_token.get_secret_value()
        if not token:
            raise HTTPException(503, "Home-Assistant-Token fehlt am Homeserver")
        self.client = httpx.AsyncClient(base_url=url + "/api/", timeout=4, follow_redirects=False,
                                       trust_env=False, headers={"Authorization": "Bearer " + token})
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()

    async def request(self, method, path, **kwargs):
        try:
            response = await self.client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError):
            # Never return upstream URLs, response bodies, or Authorization headers.
            raise HTTPException(503, "Home Assistant nicht erreichbar oder Zugriff abgelehnt") from None

    async def temperature_unit(self):
        data = await self.request("GET", "config")
        return data.get("unit_system", {}).get("temperature") if isinstance(data, dict) else None

    async def state(self, entity):
        data = await self.request("GET", "states/" + entity)
        if not isinstance(data, dict) or not isinstance(data.get("attributes"), dict) or not isinstance(data.get("state"), str):
            raise HTTPException(503, "Ungültiger Home-Assistant-Zustand")
        return data

    async def service(self, domain, service, data):
        await self.request("POST", f"services/{domain}/{service}", json=data)


def light_color(state):
    if state["state"] == "off":
        return "aus"
    rgb = state["attributes"].get("rgb_color")
    if not isinstance(rgb, (list, tuple)) or len(rgb) != 3 or any(number(x) is None or not 0 <= x <= 255 for x in rgb) or max(rgb) == 0:
        return None
    # Brightness-independent nearest palette entry, including HA's RGB conversion
    # for lights whose native mode is HS or XY.
    scaled = [x * 255 / max(rgb) for x in rgb]
    return min(COLORS, key=lambda key: sum((a-b)**2 for a,b in zip(scaled, COLORS[key])))


def normalize(entity, state, cfg, unit):
    attrs = state["attributes"]
    available = state["state"] not in {"unknown", "unavailable"}
    result = {"name": str(attrs.get("friendly_name") or entity)[:80], "available": available}
    if entity.startswith("climate."):
        low, high = number(attrs.get("min_temp")), number(attrs.get("max_temp"))
        minimum, maximum = max(cfg.minimum, low if low is not None else cfg.minimum), min(cfg.maximum, high if high is not None else cfg.maximum)
        # This UI deliberately handles Celsius single-setpoint thermostats only.
        target = number(attrs.get("temperature"))
        result.update(current=number(attrs.get("current_temperature")), target=target,
                      minimum=minimum, maximum=maximum,
                      controllable=available and unit == "°C" and target is not None and minimum <= maximum)
    else:
        modes = attrs.get("supported_color_modes") or []
        result.update(on=state["state"] == "on", colorSupported=bool(COLOR_MODES.intersection(modes)) if isinstance(modes, list) else False,
                      color=light_color(state))
    return result


async def snapshot(cfg, ha, unit):
    entities = ([cfg.climate] if cfg.climate else []) + cfg.lights
    async def read(entity):
        try:
            value = normalize(entity, await ha.state(entity), cfg, unit)
        except HTTPException:
            value = {"name": entity, "available": False, "controllable": False, "colorSupported": False}
        if entity.startswith("light."):
            value["sceneSupported"] = entity in cfg.light_scenes
        return value
    values = await asyncio.gather(*(read(entity) for entity in entities))
    return {"schemaVersion": 1, "temperatureSetSupported": True, "climate": values[0] if cfg.climate else None,
            "lights": values[1:] if cfg.climate else values, "colors": list(COLORS)}


async def read_room(device):
    cfg = configuration(device)
    async with HomeAssistant() as ha:
        return await snapshot(cfg, ha, await ha.temperature_unit())


async def command(device, cmd):
    cfg = configuration(device)
    if cmd.target == "climate":
        entity = cfg.climate
    else:
        index = int(cmd.target[-1])
        entity = cfg.lights[index] if index < len(cfg.lights) else ""
    if not entity:
        raise HTTPException(403, "Dieses Ziel ist dem Gerät nicht zugeordnet")
    async with _locks[entity], HomeAssistant() as ha:
        unit = await ha.temperature_unit()
        state = await ha.state(entity)
        normalized = normalize(entity, state, cfg, unit)
        if not normalized["available"]:
            raise HTTPException(409, "Gerät ist nicht verfügbar")
        if cmd.target == "climate":
            if not normalized["controllable"]:
                raise HTTPException(409, "Heizung benötigt eine einzelne Zieltemperatur in °C")
            current = normalized["target"]
            # Relative steps wait for the previous write; absolute selections may
            # replace an unconfirmed target without computing from stale state.
            if entity in _pending and cmd.action != "set_temperature":
                previous, sent_at = _pending[entity]
                if abs(current - previous) > .01 and time.monotonic() - sent_at < 15:
                    raise HTTPException(409, "Vorherige Zieltemperatur noch nicht bestätigt")
                _pending.pop(entity)
            target = cmd.temperature if cmd.action == "set_temperature" else current + (1 if cmd.action == "warmer" else -1)
            if not normalized["minimum"] <= target <= normalized["maximum"]:
                raise HTTPException(409, "Temperaturgrenze erreicht")
            _pending[entity] = (target, time.monotonic())  # Retain on ambiguous network failure; never blindly resend.
            await ha.service("climate", "set_temperature", {"entity_id": entity, "temperature": target})
            # Home Assistant normally updates its state during the blocking service call.
            # Only legacy relative steps stay blocked until confirmation.
        elif cmd.action == "scene":
            scene = cfg.light_scenes.get(entity)
            if not scene:
                raise HTTPException(403, "Dieser Lampe ist keine Szene zugeordnet")
            scene_state = await ha.state(scene)
            if scene_state["state"] == "unavailable":
                raise HTTPException(409, "Szene ist nicht verfügbar")
            # HA scene states may be 'unknown' before their first activation.
            await ha.service("scene", "turn_on", {"entity_id": scene})
        elif cmd.action == "color":
            if not normalized["colorSupported"]:
                raise HTTPException(409, "Diese Lampe unterstützt keine Farben")
            await ha.service("light", "turn_on", {"entity_id": entity, "rgb_color": COLORS[cmd.color]})
        else:
            await ha.service("light", "turn_" + cmd.action, {"entity_id": entity})
        result = await snapshot(cfg, ha, unit)
        climate = result.get("climate")
        confirmed = cmd.target != "climate" or (climate and climate.get("target") == target)
        if cmd.target == "climate" and confirmed:
            _pending.pop(entity, None)
        result["notice"] = "Szene gesendet" if cmd.action == "scene" else "Gesendet" if confirmed else "Warte auf Heizungsbestätigung"
        return result
