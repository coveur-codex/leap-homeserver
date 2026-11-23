"""Persist the difficulty of the shared Rangierwerk yard."""
from alembic import op
import sqlalchemy as sa

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table("rangierwerk_settings"):
        op.create_table(
            "rangierwerk_settings",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("difficulty", sa.Integer, nullable=False, server_default="1"),
            sa.CheckConstraint("id = 1", name="rangierwerk_singleton"),
            sa.CheckConstraint("difficulty BETWEEN 1 AND 4", name="rangierwerk_difficulty"),
        )


def downgrade():
    op.drop_table("rangierwerk_settings")
