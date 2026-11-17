"""Move Math Lab permissions into the new learning page, keep all legacy data."""
from alembic import op
import sqlalchemy as sa

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    devices = sa.table("devices", sa.column("id", sa.Integer), sa.column("enabled_games", sa.JSON))
    pages = sa.table("device_pages", sa.column("device_id", sa.Integer),
                     sa.column("page_id", sa.String), sa.column("title", sa.String),
                     sa.column("enabled", sa.Boolean), sa.column("position", sa.Integer),
                     sa.column("settings", sa.JSON))
    for device_id, games_enabled in bind.execute(sa.select(devices.c.id, devices.c.enabled_games)):
        existing = bind.execute(sa.select(pages).where(pages.c.device_id == device_id)).mappings().all()
        if any(page["page_id"] == "learning" for page in existing):
            continue
        games = next((page for page in existing if page["page_id"] == "games"), None)
        settings = {"applications": [{"id": "math_lab", "enabled": "math_lab" in (games_enabled or [])},
                                      {"id": "syllable_trainer", "enabled": True}]}
        # math_lab, enabled_games and all progress stay in their existing storage.
        bind.execute(pages.insert().values(device_id=device_id, page_id="learning", title="Lernwelt",
                     enabled=games["enabled"] if games else True,
                     position=max((p["position"] for p in existing), default=0) + 1, settings=settings))
        bind.execute(sa.text("UPDATE devices SET config_version=config_version+1 WHERE id=:id"), {"id": device_id})


def downgrade():
    op.execute(sa.text("DELETE FROM device_pages WHERE page_id='learning'"))
    op.execute(sa.text("UPDATE devices SET config_version=config_version+1"))
