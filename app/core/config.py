from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="LEAP_", extra="ignore")
    data_dir: Path = Path("./data")
    database_url: str = "sqlite:///./data/database/leap.db"
    seed_demo_data: bool = False
    allow_private_feeds: bool = False
    fetch_opengraph: bool = False
    admin_auth: bool = False
    admin_username: str = "admin"
    admin_password: str = "change-me"
    news_retention_days: int = 14
    log_level: str = "INFO"
    weather_cache_minutes: int = 15
    aircraft_radius_nm: int = 25
    aircraft_limit: int = 20
    aircraft_provider_url: str = "https://api.adsb.lol/v2/lat/{latitude}/lon/{longitude}/dist/{radius}"
    request_timeout: float = 10.0
    max_download_bytes: int = 8_000_000

settings = Settings()
for name in ("database", "cache", "images", "logs"):
    (settings.data_dir / name).mkdir(parents=True, exist_ok=True)
