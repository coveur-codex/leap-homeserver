"""Per-device WLAN profiles and number decomposition targets."""
from alembic import op
import sqlalchemy as sa
revision = "0020"
down_revision = "0019"
branch_labels = depends_on = None

def upgrade():
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("devices")}
    if "network_config" not in columns:
        op.add_column("devices", sa.Column("network_config", sa.JSON(), nullable=False, server_default="{}"))
    if "math_lab" not in columns:
        op.add_column("devices", sa.Column("math_lab", sa.JSON(), nullable=False, server_default='{"targets":[10]}'))
    op.execute(sa.text("UPDATE devices SET config_version=config_version+1"))

def downgrade():
    op.drop_column("devices", "math_lab")
    op.drop_column("devices", "network_config")
