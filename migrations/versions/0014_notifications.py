"""Notification sounds, observer altitude and immutable sender color."""
from alembic import op
import sqlalchemy as sa
revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

def upgrade():
    for table, columns in {
        "devices": [sa.Column("location_altitude_meters", sa.Float(), nullable=True),
                    sa.Column("notification_sounds", sa.JSON(), nullable=False, server_default='{"communication":true,"news":true,"aircraft":true}')],
        "communication_relay_events": [sa.Column("accent_color", sa.String(7), nullable=False, server_default="#00d7c5")],
    }.items():
        existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}
        for column in columns:
            if column.name not in existing: op.add_column(table, column)

def downgrade():
    op.drop_column("communication_relay_events", "accent_color")
    op.drop_column("devices", "notification_sounds")
    op.drop_column("devices", "location_altitude_meters")
