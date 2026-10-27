import math
from datetime import datetime, timezone

import httpx

from app.core.config import settings
from app.services.aircraft_names import AIRCRAFT_TYPES, airport_name


def _distance_nm(latitude: float, longitude: float, aircraft_latitude: float, aircraft_longitude: float) -> float:
    """Return the great-circle distance in nautical miles."""
    lat1, lat2 = math.radians(latitude), math.radians(aircraft_latitude)
    dlat = lat2 - lat1
    dlon = math.radians(aircraft_longitude - longitude)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    a = max(0.0, min(1.0, a))
    return 3440.065 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


class AdsbLolProvider:
    async def nearby(self, latitude: float, longitude: float, radius_nm: int) -> dict:
        url = settings.aircraft_provider_url.format(latitude=latitude, longitude=longitude, radius=radius_nm)
        async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
            response = await client.get(url, headers={"User-Agent": "LEAP-HomeServer/1.0"})
            response.raise_for_status()
            raw = response.json()

        aircraft = []
        for item in raw.get("ac", []):
            lat, lon = item.get("lat"), item.get("lon")
            if (not isinstance(lat, (int, float)) or not isinstance(lon, (int, float))
                    or not math.isfinite(lat) or not math.isfinite(lon) or abs(lat) > 90 or abs(lon) > 180):
                continue
            distance = _distance_nm(latitude, longitude, lat, lon)
            if distance > radius_nm:
                continue
            altitude = _number(item.get("alt_baro"))
            speed = _number(item.get("gs"))
            if speed is not None and speed < 0:
                speed = None
            heading = _number(item.get("track"))
            route = item.get("route") if isinstance(item.get("route"), dict) else {}
            aircraft.append({
                "typeName": AIRCRAFT_TYPES.get(str(item.get("t") or "").upper(), "Unbekannter Flugzeugtyp"),
                "originName": airport_name(item.get("origin") or route.get("origin")),
                "destinationName": airport_name(item.get("destination") or route.get("destination")),
                "positionAgeSeconds": max(0, item["seen_pos"]) if isinstance(item.get("seen_pos"), (int, float)) and math.isfinite(item["seen_pos"]) else 0,
                "altitudeMeters": round(altitude * 0.3048) if isinstance(altitude, (int, float)) else None,
                "groundSpeedKmh": round(speed * 1.852) if speed is not None else None,
                "distanceKm": round(distance * 1.852, 1),
                "hex": str(item.get("hex", "")).removeprefix("~"),
                "callsign": str(item.get("flight") or "").strip(),
                "registration": item.get("r"),
                "type": item.get("t"),
                "latitude": round(float(lat), 5),
                "longitude": round(float(lon), 5),
                "altitudeFeet": altitude if isinstance(altitude, (int, float)) else None,
                "groundSpeedKnots": speed,
                "trackDegrees": heading,
                "distanceNm": round(distance, 1),
            })
        aircraft.sort(key=lambda item: item["distanceNm"])
        return {"updated": datetime.now(timezone.utc).isoformat(), "radiusNm": radius_nm, "radiusKm": round(radius_nm * 1.852, 1), "center": {"latitude": latitude, "longitude": longitude}, "aircraft": aircraft[:settings.aircraft_limit]}
