"""Persist location request reservations and retry pauses."""
from alembic import op
import sqlalchemy as sa

revision = "0021"
down_revision = "0020"
branch_labels = depends_on = None


def upgrade():
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("location_cache")}
    for name in ("weather_next_attempt_at", "aircraft_next_attempt_at"):
        if name not in columns:
            op.add_column("location_cache", sa.Column(name, sa.DateTime(timezone=True), nullable=True))


def downgrade():
    for name in ("aircraft_next_attempt_at", "weather_next_attempt_at"):
        op.drop_column("location_cache", name)
