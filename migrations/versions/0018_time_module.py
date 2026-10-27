"""Enable the local time module on existing devices without reordering pages."""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    pages = sa.table("device_pages", sa.column("device_id", sa.Integer),
                     sa.column("page_id", sa.String), sa.column("title", sa.String),
                     sa.column("enabled", sa.Boolean), sa.column("position", sa.Integer),
                     sa.column("settings", sa.JSON))
    for device_id in bind.execute(sa.text("SELECT id FROM devices")).scalars().all():
        rows = bind.execute(sa.select(pages.c.page_id, pages.c.position).where(pages.c.device_id == device_id)).all()
        if not any(row.page_id == "time" for row in rows):
            bind.execute(pages.insert().values(device_id=device_id, page_id="time", title="Zeit", enabled=True,
                                              position=max((row.position for row in rows), default=0) + 1, settings={}))
    op.execute(sa.text("UPDATE devices SET config_version=config_version+1"))


def downgrade():
    op.execute(sa.text("DELETE FROM device_pages WHERE page_id='time'"))
    op.execute(sa.text("UPDATE devices SET config_version=config_version+1"))
