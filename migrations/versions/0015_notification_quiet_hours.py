"""Per-device quiet hours for notification sounds."""
from alembic import op
import sqlalchemy as sa
revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

def upgrade():
    if "notification_quiet_hours" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("devices")}:
        op.add_column("devices", sa.Column("notification_quiet_hours", sa.JSON(), nullable=False, server_default="{}"))

def downgrade():
    op.drop_column("devices", "notification_quiet_hours")
