"""Offline device photo albums and immutable sender portraits."""
from alembic import op
import sqlalchemy as sa
from app.models import ChillPhoto
revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    ChillPhoto.__table__.create(bind, checkfirst=True)
    columns = {c["name"] for c in sa.inspect(bind).get_columns("devices")}
    if "chill_album_id" not in columns:
        op.add_column("devices", sa.Column("chill_album_id", sa.String(100), nullable=False, server_default=""))
    if "chill_photos" not in columns:
        op.add_column("devices", sa.Column("chill_photos", sa.JSON(), nullable=False, server_default="[]"))
    if "avatar_image" not in {c["name"] for c in sa.inspect(bind).get_columns("communication_relay_events")}:
        op.add_column("communication_relay_events", sa.Column("avatar_image", sa.String(64), nullable=False, server_default=""))
    op.execute(sa.text("UPDATE devices SET config_version=config_version+1"))


def downgrade():
    op.drop_column("communication_relay_events", "avatar_image")
    op.drop_column("devices", "chill_photos")
    op.drop_column("devices", "chill_album_id")
    op.drop_table("chill_photos")
