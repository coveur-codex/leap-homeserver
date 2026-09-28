from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models import Device, WeatherCache
class WeatherProvider(ABC):
    @abstractmethod
    async def current(self,latitude:float,longitude:float,unit:str)->dict: ...
class OpenMeteoProvider(WeatherProvider):
    async def current(self,latitude:float,longitude:float,unit:str)->dict:
        params={"latitude":latitude,"longitude":longitude,"current":"temperature_2m,weather_code,wind_speed_10m","daily":"temperature_2m_max,temperature_2m_min,precipitation_probability_max","forecast_days":1,"timezone":"auto","temperature_unit":"fahrenheit" if unit=="F" else "celsius"}
        async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
            response=await client.get("https://api.open-meteo.com/v1/forecast",params=params); response.raise_for_status(); raw=response.json()
        return {"updated":datetime.now(timezone.utc).isoformat(),"current":{"temperature":raw["current"]["temperature_2m"],"weatherCode":raw["current"]["weather_code"],"windSpeed":raw["current"]["wind_speed_10m"]},"today":{"min":raw["daily"]["temperature_2m_min"][0],"max":raw["daily"]["temperature_2m_max"][0],"precipitationProbability":raw["daily"]["precipitation_probability_max"][0]}}
async def get_weather(device:Device,db:Session,provider:WeatherProvider|None=None)->dict:
    cache=db.scalar(select(WeatherCache).where(WeatherCache.device_id==device.id)); now=datetime.now(timezone.utc)
    if cache and cache.fetched_at.replace(tzinfo=timezone.utc)>now-timedelta(minutes=settings.weather_cache_minutes): return {**cache.data,"stale":False}
    if device.latitude is None or device.longitude is None: raise ValueError("Wetterort ist nicht konfiguriert")
    try:
        data=await (provider or OpenMeteoProvider()).current(device.latitude,device.longitude,device.temperature_unit); data["location"]=device.weather_location
        if cache: cache.data=data; cache.fetched_at=now
        else: db.add(WeatherCache(device_id=device.id,data=data,fetched_at=now))
        device.weather_version+=1; db.commit(); return {**data,"stale":False}
    except Exception:
        if cache: return {**cache.data,"stale":True}
        raise
