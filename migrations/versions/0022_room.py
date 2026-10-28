"""Append room controls and initial household assignments, preserving existing pages."""
from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

# Freeze initial household data in this migration; no runtime-service imports.
ROOMS = {
    "leap-papa": ("climate.heizung_homeoffice", []),
    "leap-erik": ("climate.heizung_lars_erik", ["light.einfahrt_garage", "light.erik_tisch"]),
    "leap-lars": ("climate.heizung_lars_erik", ["light.lars_hochbett", "light.lars_tisch"]),
    "leap-anna": ("climate.trv_z01_80_7", ["light.lichterkette_anna"]),
}


def upgrade():
    bind = op.get_bind()
    pages = sa.table("device_pages", sa.column("device_id"), sa.column("page_id"), sa.column("title"),
                     sa.column("enabled", sa.Boolean), sa.column("position"), sa.column("settings", sa.JSON))
    for did, name in bind.execute(sa.text("SELECT id, device_id FROM devices")):
        if bind.execute(sa.text("SELECT id FROM device_pages WHERE device_id=:id AND page_id='room'"), {"id": did}).first():
            continue
        position = bind.execute(sa.text("SELECT COALESCE(MAX(position),0)+1 FROM device_pages WHERE device_id=:id"), {"id": did}).scalar()
        climate, lights = ROOMS.get(name, ("", []))
        bind.execute(pages.insert().values(device_id=did, page_id="room", title="Mein Zimmer", enabled=name in ROOMS,
                                          position=position, settings={"climate": climate, "lights": lights, "minimum": 10, "maximum": 30}))
        bind.execute(sa.text("UPDATE devices SET config_version=config_version+1 WHERE id=:id"), {"id": did})


def downgrade():
    op.execute(sa.text("DELETE FROM device_pages WHERE page_id='room'"))
    op.execute(sa.text("UPDATE devices SET config_version=config_version+1"))
