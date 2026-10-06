"""Per-device offline math quiz configuration."""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    if "math_quiz" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("devices")}:
        op.add_column("devices", sa.Column("math_quiz", sa.JSON(), nullable=False,
            server_default='{"operation":"add","limit":20}'))
    op.execute(sa.text("UPDATE devices SET config_version=config_version+1"))


def downgrade():
    op.drop_column("devices", "math_quiz")
