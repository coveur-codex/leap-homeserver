"""add per-device knowledge settings"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("devices")}
    if "knowledge_source" not in columns:
        op.add_column("devices", sa.Column("knowledge_source", sa.String(length=20), nullable=False, server_default="klexikon"))
    if "knowledge_version" not in columns:
        op.add_column("devices", sa.Column("knowledge_version", sa.Integer(), nullable=False, server_default="1"))


def downgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("devices")}
    if "knowledge_version" in columns:
        op.drop_column("devices", "knowledge_version")
    if "knowledge_source" in columns:
        op.drop_column("devices", "knowledge_source")
