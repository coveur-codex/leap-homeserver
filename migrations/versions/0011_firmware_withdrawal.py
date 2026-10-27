"""Allow firmware withdrawal and deletion while preserving release identities."""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("firmware_releases")}
    for name in ("withdrawn", "deleted"):
        if name not in columns:
            op.add_column("firmware_releases", sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("firmware_releases", "deleted")
    op.drop_column("firmware_releases", "withdrawn")
