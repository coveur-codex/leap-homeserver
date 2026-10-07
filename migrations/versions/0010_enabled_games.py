"""Per-device built-in game selection, retaining the previously visible games."""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    # 0001 uses current metadata when creating a fresh database.
    if "enabled_games" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("devices")}:
        op.add_column("devices", sa.Column("enabled_games", sa.JSON(), nullable=False,
            server_default='["tamagotchi", "snake", "hot_potato", "simon_motion", "tilt_maze", "connect_four", "kitchen", "crab_journey"]'))
    op.execute(sa.text("UPDATE devices SET config_version=config_version+1"))


def downgrade():
    op.drop_column("devices", "enabled_games")
