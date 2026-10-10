from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, Table, Column, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .core.database import Base
from .core.games import DEFAULT_GAMES

def now(): return datetime.now(timezone.utc)

device_categories = Table("device_categories", Base.metadata,
    Column("device_id", ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True),
    Column("category_id", ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True))
device_quiz_catalogs = Table("device_quiz_catalogs", Base.metadata,
    Column("device_id", ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True),
    Column("catalog_id", ForeignKey("quiz_catalogs.id", ondelete="CASCADE"), primary_key=True))

class Device(Base):
    __tablename__="devices"
    id: Mapped[int]=mapped_column(primary_key=True)
    device_id: Mapped[str]=mapped_column(String(80), unique=True, index=True)
    name: Mapped[str]=mapped_column(String(100)); child_name: Mapped[str]=mapped_column(String(100), default="")
    age: Mapped[int]=mapped_column(Integer, default=8); avatar: Mapped[str]=mapped_column(String(100), default="dragon")
    avatar_name: Mapped[str]=mapped_column(String(100), default="")
    accent_color: Mapped[str] = mapped_column(String(7), default="#00d7c5", server_default="#00d7c5")
    communication_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    math_quiz: Mapped[dict] = mapped_column(JSON, default=lambda:{"operation":"add", "limit":20}, server_default='{"operation":"add","limit":20}')
    avatar_config: Mapped[dict]=mapped_column(JSON, default=dict); enabled: Mapped[bool]=mapped_column(Boolean, default=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=now); updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    config_version: Mapped[int]=mapped_column(Integer, default=1); news_version: Mapped[int]=mapped_column(Integer, default=1)
    weather_version: Mapped[int]=mapped_column(Integer, default=1); aircraft_version: Mapped[int]=mapped_column(Integer, default=1); quiz_version: Mapped[int]=mapped_column(Integer, default=1)
    last_seen: Mapped[datetime|None]=mapped_column(DateTime(timezone=True)); firmware_version: Mapped[str|None]=mapped_column(String(40))
    firmware_channel: Mapped[str] = mapped_column(String(10), default="stable")
    confirmed_firmware: Mapped[str|None] = mapped_column(String(40))
    last_sync: Mapped[datetime|None] = mapped_column(DateTime(timezone=True))
    installed_assets: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled_games: Mapped[list] = mapped_column(JSON, default=lambda: list(DEFAULT_GAMES))
    content_selection: Mapped[list] = mapped_column(JSON, default=list)
    battery: Mapped[int|None]=mapped_column(Integer); wifi_rssi: Mapped[int|None]=mapped_column(Integer); free_flash: Mapped[int|None]=mapped_column(Integer)
    memory_usage: Mapped[dict|None] = mapped_column(JSON)
    news_limit: Mapped[int]=mapped_column(Integer, default=20); news_max_age_hours: Mapped[int]=mapped_column(Integer, default=48)
    included_feed_ids: Mapped[list]=mapped_column(JSON, default=list); excluded_feed_ids: Mapped[list]=mapped_column(JSON, default=list)
    weather_location: Mapped[str]=mapped_column(String(120), default=""); latitude: Mapped[float|None]=mapped_column(Float); longitude: Mapped[float|None]=mapped_column(Float)
    temperature_unit: Mapped[str]=mapped_column(String(2), default="C"); weather_fields: Mapped[list]=mapped_column(JSON, default=lambda:["temperature","rain","wind"])
    knowledge_source: Mapped[str]=mapped_column(String(20), default="klexikon")
    knowledge_version: Mapped[int]=mapped_column(Integer, default=1)
    home_slots: Mapped[dict]=mapped_column(JSON, default=lambda:{"slot1":"weather","slot2":"news_count","slot3":"question_of_day","slot4":"none"})
    pages: Mapped[list["DevicePage"]]=relationship(cascade="all, delete-orphan", order_by="DevicePage.position")
    categories: Mapped[list["Category"]]=relationship(secondary=device_categories)
    quiz_catalogs: Mapped[list["QuizCatalog"]]=relationship(secondary=device_quiz_catalogs)
class DevicePage(Base):
    __tablename__="device_pages"; __table_args__=(UniqueConstraint("device_id","page_id"),)
    id: Mapped[int]=mapped_column(primary_key=True); device_id: Mapped[int]=mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    page_id: Mapped[str]=mapped_column(String(40)); title: Mapped[str]=mapped_column(String(80)); enabled: Mapped[bool]=mapped_column(Boolean, default=True)
    position: Mapped[int]=mapped_column(Integer); settings: Mapped[dict]=mapped_column(JSON, default=dict)
class Category(Base):
    __tablename__="categories"; id: Mapped[int]=mapped_column(primary_key=True); slug: Mapped[str]=mapped_column(String(60), unique=True); name: Mapped[str]=mapped_column(String(100))
class Feed(Base):
    __tablename__="feeds"; id: Mapped[int]=mapped_column(primary_key=True); name: Mapped[str]=mapped_column(String(120)); url: Mapped[str]=mapped_column(String(1000), unique=True)
    enabled: Mapped[bool]=mapped_column(Boolean, default=True); category_id: Mapped[int|None]=mapped_column(ForeignKey("categories.id")); category: Mapped[Category|None]=relationship()
    update_interval: Mapped[int]=mapped_column(Integer, default=15); last_fetch: Mapped[datetime|None]=mapped_column(DateTime(timezone=True)); last_success: Mapped[datetime|None]=mapped_column(DateTime(timezone=True)); last_error: Mapped[str|None]=mapped_column(Text)
    auto_publish: Mapped[bool]=mapped_column(Boolean, default=True); image_mode: Mapped[str]=mapped_column(String(20), default="center_crop")
class Article(Base):
    __tablename__="articles"; id: Mapped[int]=mapped_column(primary_key=True); external_id: Mapped[str|None]=mapped_column(String(1000)); feed_id: Mapped[int]=mapped_column(ForeignKey("feeds.id", ondelete="CASCADE")); feed: Mapped[Feed]=relationship()
    category: Mapped[str]=mapped_column(String(60), default="allgemein"); title: Mapped[str]=mapped_column(String(500)); summary: Mapped[str]=mapped_column(Text); content: Mapped[str]=mapped_column(Text, default="")
    source: Mapped[str]=mapped_column(String(120)); url: Mapped[str]=mapped_column(String(1500)); published_at: Mapped[datetime]=mapped_column(DateTime(timezone=True)); fetched_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=now)
    image_original: Mapped[str|None]=mapped_column(String(500)); image_leap: Mapped[str|None]=mapped_column(String(500)); hash: Mapped[str]=mapped_column(String(64), unique=True, index=True)
class WeatherCache(Base):
    __tablename__="weather_cache"; id: Mapped[int]=mapped_column(primary_key=True); device_id: Mapped[int]=mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), unique=True); fetched_at: Mapped[datetime]=mapped_column(DateTime(timezone=True)); data: Mapped[dict]=mapped_column(JSON)
class LocationCache(Base):
    __tablename__="location_cache"
    id: Mapped[int]=mapped_column(primary_key=True)
    location_key: Mapped[str]=mapped_column(String(80), unique=True, index=True)
    location: Mapped[str]=mapped_column(String(120), default="")
    latitude: Mapped[float]=mapped_column(Float); longitude: Mapped[float]=mapped_column(Float)
    weather_fetched_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True)); weather_data: Mapped[dict|None]=mapped_column(JSON)
    weather_error: Mapped[str|None]=mapped_column(Text)
    aircraft_fetched_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True)); aircraft_data: Mapped[dict|None]=mapped_column(JSON)
    aircraft_error: Mapped[str|None]=mapped_column(Text)
class QuizCatalog(Base):
    __tablename__="quiz_catalogs"; id: Mapped[int]=mapped_column(primary_key=True); name: Mapped[str]=mapped_column(String(120)); enabled: Mapped[bool]=mapped_column(Boolean, default=True); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=now); questions: Mapped[list["QuizQuestion"]]=relationship(cascade="all, delete-orphan")
class QuizQuestion(Base):
    __tablename__="quiz_questions"; id: Mapped[int]=mapped_column(primary_key=True); catalog_id: Mapped[int]=mapped_column(ForeignKey("quiz_catalogs.id", ondelete="CASCADE")); question: Mapped[str]=mapped_column(Text); answers: Mapped[list]=mapped_column(JSON); explanation: Mapped[str]=mapped_column(Text, default=""); min_age: Mapped[int]=mapped_column(Integer, default=0); difficulty: Mapped[int]=mapped_column(Integer, default=1); tags: Mapped[list]=mapped_column(JSON, default=list)

class AssetPackage(Base):
    __tablename__ = "asset_packages"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[str] = mapped_column(String(120))
    current_version: Mapped[int] = mapped_column(Integer, default=0)
    catalog_id: Mapped[int|None] = mapped_column(ForeignKey("quiz_catalogs.id"), unique=True)

class AssetVersion(Base):
    __tablename__ = "asset_versions"
    __table_args__ = (UniqueConstraint("package_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    package_id: Mapped[str] = mapped_column(ForeignKey("asset_packages.id"))
    version: Mapped[int] = mapped_column(Integer)
    manifest: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class FirmwareRelease(Base):
    __tablename__ = "firmware_releases"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(40), unique=True)
    channel: Mapped[str] = mapped_column(String(10))
    withdrawn: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    notes: Mapped[str] = mapped_column(Text, default="")
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class SyncRun(Base):
    __tablename__ = "sync_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    plan: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(40), default="offered")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class SyncEvent(Base):
    __tablename__ = "sync_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("sync_runs.id", ondelete="CASCADE"), index=True)
    event: Mapped[str] = mapped_column(String(40))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CommunicationMessage(Base):
    """Global prepared messages, not chat history."""
    __tablename__ = "communication_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    text: Mapped[str] = mapped_column(String(120))
    symbol: Mapped[str] = mapped_column(String(16), default="")
    position: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"
    __table_args__ = (UniqueConstraint("device_id", "event_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSON)
    correct: Mapped[bool] = mapped_column(Boolean)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CommunicationRelayEvent(Base):
    """Server-owned snapshots, shared by all enabled communication participants."""
    __tablename__ = "communication_relay_events"
    __table_args__ = (UniqueConstraint("sender_id", "event_id"), {"sqlite_autoincrement": True})
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sender_id: Mapped[str] = mapped_column(String(80))
    event_id: Mapped[str] = mapped_column(String(64))
    template_id: Mapped[str] = mapped_column(String(36))
    name: Mapped[str] = mapped_column(String(100))
    text: Mapped[str] = mapped_column(String(120))
    symbol: Mapped[str] = mapped_column(String(16))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
