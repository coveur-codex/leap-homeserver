"""add configurable avatar name"""
from alembic import op
import sqlalchemy as sa

revision="0002"
down_revision="0001"
branch_labels=None
depends_on=None

def upgrade():
    columns={column["name"] for column in sa.inspect(op.get_bind()).get_columns("devices")}
    if "avatar_name" not in columns:
        op.add_column("devices", sa.Column("avatar_name", sa.String(length=100), nullable=False, server_default=""))

def downgrade():
    columns={column["name"] for column in sa.inspect(op.get_bind()).get_columns("devices")}
    if "avatar_name" in columns:
        op.drop_column("devices", "avatar_name")
