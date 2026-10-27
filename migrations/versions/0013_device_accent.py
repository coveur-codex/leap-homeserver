"""Configurable device accent colour."""
from alembic import op
import sqlalchemy as sa
revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

def upgrade():
    if "accent_color" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("devices")}:
        op.add_column("devices", sa.Column("accent_color", sa.String(7), nullable=False, server_default="#00d7c5"))

def downgrade():
    op.drop_column("devices", "accent_color")
