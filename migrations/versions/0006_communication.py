"""Global communication templates and per-device participation."""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "communication_enabled" not in {c["name"] for c in sa.inspect(bind).get_columns("devices")}:
        op.add_column("devices", sa.Column("communication_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    if "communication_messages" not in sa.inspect(bind).get_table_names():
        op.create_table("communication_messages",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("text", sa.String(120), nullable=False),
            sa.Column("symbol", sa.String(16), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False))
    # Append without disturbing any existing page order or settings.
    op.execute(sa.text("""INSERT INTO device_pages (device_id, page_id, title, enabled, position, settings)
        SELECT d.id, 'communication', 'Kommunikation', d.communication_enabled,
            COALESCE((SELECT MAX(p.position) FROM device_pages p WHERE p.device_id=d.id), 0)+1, '{}'
        FROM devices d WHERE NOT EXISTS
            (SELECT 1 FROM device_pages p WHERE p.device_id=d.id AND p.page_id='communication')"""))
    op.execute(sa.text("UPDATE devices SET config_version=config_version+1"))


def downgrade():
    op.execute(sa.text("DELETE FROM device_pages WHERE page_id='communication'"))
    op.drop_table("communication_messages")
    op.drop_column("devices", "communication_enabled")
