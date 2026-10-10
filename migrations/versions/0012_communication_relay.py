"""Durable communication relay with monotonic cursors and idempotent sends."""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    if "communication_relay_events" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table("communication_relay_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("sender_id", sa.String(80), nullable=False),
            sa.Column("event_id", sa.String(64), nullable=False),
            sa.Column("template_id", sa.String(36), nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("text", sa.String(120), nullable=False),
            sa.Column("symbol", sa.String(16), nullable=False),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("sender_id", "event_id"), sqlite_autoincrement=True)
        op.create_index("ix_communication_relay_events_sent_at", "communication_relay_events", ["sent_at"])


def downgrade():
    op.drop_table("communication_relay_events")
