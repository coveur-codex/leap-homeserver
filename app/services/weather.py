from abc import ABC, abstractmethod
from datetime import datetime, timezone

import httpx

from app.core.config import settings


class WeatherProvider(ABC):
    @abstractmethod
    async def current(self, latitude: float, longitude: float, unit: str) -> dict: ...


class OpenMeteoProvider(WeatherProvider):
    async def current(self, latitude: float, longitude: float, unit: str) -> dict:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,weather_code,wind_speed_10m,is_day",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
            "forecast_days": 2,
            "wind_speed_unit": "kmh",
            "timezone": "auto",
            "temperature_unit": "fahrenheit" if unit == "F" else "celsius",
        }
        async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
            response = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
            response.raise_for_status()
            raw = response.json()
        daily = raw.get("daily", {})
        def day(index):
            def value(key):
                values = daily.get(key, [])
                return values[index] if isinstance(values, list) and len(values) > index else None
            if value("time") is None:
                return None
            return {"date": value("time"), "weatherCode": value("weather_code"),
                    "min": value("temperature_2m_min"), "max": value("temperature_2m_max"),
                    "precipitationProbability": value("precipitation_probability_max")}
        return {
            "updated": datetime.now(timezone.utc).isoformat(),
            "unit": unit,
            "timezone": raw.get("timezone"),
            "current": {
                "temperature": raw["current"]["temperature_2m"],
                "weatherCode": raw["current"]["weather_code"],
                "windSpeed": raw["current"].get("wind_speed_10m"),
                "isDay": bool(raw["current"]["is_day"]) if raw["current"].get("is_day") in (0, 1) else None,
            },
            "today": day(0),
            "tomorrow": day(1),
        }
