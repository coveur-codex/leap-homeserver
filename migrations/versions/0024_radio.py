"""Central radio stations and device grants; radio defaults to disabled."""
from alembic import op
import sqlalchemy as sa
revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    if "radio_station_ids" not in {c["name"] for c in sa.inspect(bind).get_columns("devices")}:
        op.add_column("devices", sa.Column("radio_station_ids", sa.JSON(), nullable=False, server_default="[]"))
    if "radio_stations" not in sa.inspect(bind).get_table_names():
        op.create_table("radio_stations", sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("url", sa.String(1000), nullable=False, unique=True),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False))
    op.execute(sa.text("""INSERT INTO device_pages (device_id, page_id, title, enabled, position, settings)
        SELECT d.id, 'radio', 'Radio', 0,
            COALESCE((SELECT MAX(p.position) FROM device_pages p WHERE p.device_id=d.id), 0)+1, '{}'
        FROM devices d WHERE NOT EXISTS
            (SELECT 1 FROM device_pages p WHERE p.device_id=d.id AND p.page_id='radio')"""))
    op.execute(sa.text("UPDATE devices SET config_version=config_version+1"))

def downgrade():
    op.execute(sa.text("DELETE FROM device_pages WHERE page_id='radio'"))
    op.drop_table("radio_stations")
    op.drop_column("devices", "radio_station_ids")
