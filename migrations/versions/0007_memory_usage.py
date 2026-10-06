"""Device memory usage reported at check-in."""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("devices")}
    if "memory_usage" not in columns:
        op.add_column("devices", sa.Column("memory_usage", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("devices", "memory_usage")
