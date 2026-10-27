"""Immutable device quiz answer snapshots."""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    # 0001 uses current metadata for new installations.
    if "quiz_attempts" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table("quiz_attempts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False),
            sa.Column("event_id", sa.String(64), nullable=False),
            sa.Column("snapshot", sa.JSON(), nullable=False),
            sa.Column("correct", sa.Boolean(), nullable=False),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("device_id", "event_id"))
        op.create_index("ix_quiz_attempts_device_id", "quiz_attempts", ["device_id"])


def downgrade():
    op.drop_table("quiz_attempts")
