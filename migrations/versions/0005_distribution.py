"""Versioned assets, firmware releases and boot sync history; preserve quiz tables."""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = depends_on = None


def upgrade():
    if op.get_bind().dialect.name != "sqlite":
        op.alter_column("devices", "avatar", existing_type=sa.String(40), type_=sa.String(100))
    for column in [
        sa.Column("firmware_channel", sa.String(10), nullable=False, server_default="stable"),
        sa.Column("confirmed_firmware", sa.String(40)),
        sa.Column("last_sync", sa.DateTime(timezone=True)),
        sa.Column("installed_assets", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("content_selection", sa.JSON(), nullable=False, server_default="[]"),
    ]:
        if column.name not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("devices")} :
            op.add_column("devices", column)
    # 0001 uses current metadata on a fresh installation.
    if "asset_packages" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table("asset_packages", sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("kind", sa.String(40), nullable=False), sa.Column("name", sa.String(120), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("catalog_id", sa.Integer(), sa.ForeignKey("quiz_catalogs.id"), unique=True))
    op.create_index("ix_asset_packages_kind", "asset_packages", ["kind"])
    op.create_table("asset_versions", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("package_id", sa.String(100), sa.ForeignKey("asset_packages.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("package_id", "version"))
    op.create_table("firmware_releases", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.String(40), unique=True, nullable=False), sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False), sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("sync_runs", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False), sa.Column("status", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_sync_runs_device_id", "sync_runs", ["device_id"])
    op.create_table("sync_events", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("sync_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event", sa.String(40), nullable=False), sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_sync_events_run_id", "sync_events", ["run_id"])


def downgrade():
    for name in ("sync_events", "sync_runs", "firmware_releases", "asset_versions", "asset_packages"):
        op.drop_table(name)
    for name in ("content_selection", "installed_assets", "last_sync", "confirmed_firmware", "firmware_channel"):
        op.drop_column("devices", name)
