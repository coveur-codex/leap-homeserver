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
            "current": "temperature_2m,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "forecast_days": 1,
            "timezone": "auto",
            "temperature_unit": "fahrenheit" if unit == "F" else "celsius",
        }
        async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
            response = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
            response.raise_for_status()
            raw = response.json()
        return {
            "updated": datetime.now(timezone.utc).isoformat(),
            "unit": unit,
            "current": {
                "temperature": raw["current"]["temperature_2m"],
                "weatherCode": raw["current"]["weather_code"],
                "windSpeed": raw["current"]["wind_speed_10m"],
            },
            "today": {
                "min": raw["daily"]["temperature_2m_min"][0],
                "max": raw["daily"]["temperature_2m_max"][0],
                "precipitationProbability": raw["daily"]["precipitation_probability_max"][0],
            },
        }
