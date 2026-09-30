"""add shared location data and aircraft versions"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    device_columns = {column["name"] for column in inspector.get_columns("devices")}
    if "aircraft_version" not in device_columns:
        op.add_column("devices", sa.Column("aircraft_version", sa.Integer(), nullable=False, server_default="1"))
    if "location_cache" in inspector.get_table_names():
        return
    op.create_table(
        "location_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("location_key", sa.String(length=80), nullable=False),
        sa.Column("location", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("weather_fetched_at", sa.DateTime(timezone=True)),
        sa.Column("weather_data", sa.JSON()),
        sa.Column("weather_error", sa.Text()),
        sa.Column("aircraft_fetched_at", sa.DateTime(timezone=True)),
        sa.Column("aircraft_data", sa.JSON()),
        sa.Column("aircraft_error", sa.Text()),
    )
    op.create_index("ix_location_cache_location_key", "location_cache", ["location_key"], unique=True)


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if "location_cache" in inspector.get_table_names():
        op.drop_index("ix_location_cache_location_key", table_name="location_cache")
        op.drop_table("location_cache")
    if "aircraft_version" in {column["name"] for column in inspector.get_columns("devices")}:
        op.drop_column("devices", "aircraft_version")
