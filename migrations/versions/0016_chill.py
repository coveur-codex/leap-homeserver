"""Per-device LoremFlickr topic; existing content selections remain unchanged."""
from alembic import op
import sqlalchemy as sa
revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade():
    if "chill_keyword" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("devices")}:
        op.add_column("devices", sa.Column("chill_keyword", sa.String(80), nullable=False, server_default="nature"))
    op.execute(sa.text("UPDATE devices SET config_version=config_version+1"))


def downgrade():
    op.drop_column("devices", "chill_keyword")
