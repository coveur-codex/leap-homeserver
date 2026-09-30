import math
from datetime import datetime, timezone

import httpx

from app.core.config import settings


def _distance_nm(latitude: float, longitude: float, aircraft_latitude: float, aircraft_longitude: float) -> float:
    """Return the great-circle distance in nautical miles."""
    lat1, lat2 = math.radians(latitude), math.radians(aircraft_latitude)
    dlat = lat2 - lat1
    dlon = math.radians(aircraft_longitude - longitude)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 3440.065 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


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
            if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
                continue
            distance = _distance_nm(latitude, longitude, lat, lon)
            if distance > radius_nm:
                continue
            altitude = item.get("alt_baro")
            aircraft.append({
                "hex": str(item.get("hex", "")).removeprefix("~"),
                "callsign": str(item.get("flight") or "").strip(),
                "registration": item.get("r"),
                "type": item.get("t"),
                "latitude": round(float(lat), 5),
                "longitude": round(float(lon), 5),
                "altitudeFeet": altitude if isinstance(altitude, (int, float)) else None,
                "groundSpeedKnots": item.get("gs") if isinstance(item.get("gs"), (int, float)) else None,
                "trackDegrees": item.get("track") if isinstance(item.get("track"), (int, float)) else None,
                "distanceNm": round(distance, 1),
            })
        aircraft.sort(key=lambda item: item["distanceNm"])
        return {"updated": datetime.now(timezone.utc).isoformat(), "radiusNm": radius_nm, "aircraft": aircraft[:settings.aircraft_limit]}
