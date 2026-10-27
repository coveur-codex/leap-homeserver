"""Shared finance cache and opt-in page; existing pages/data remain intact."""
from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade():
    if "finance_cache" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table("finance_cache",
            sa.Column("key", sa.String(80), primary_key=True),
            sa.Column("provider", sa.String(20), nullable=False),
            sa.Column("symbol", sa.String(32), nullable=False),
            sa.Column("data", sa.JSON(), nullable=False),
            sa.Column("fetched_at", sa.DateTime(timezone=True)),
            sa.Column("next_fetch", sa.DateTime(timezone=True)),
            sa.Column("news_at", sa.DateTime(timezone=True)),
            sa.Column("error", sa.Text()), sa.Column("news_error", sa.Text()))
    op.execute(sa.text("""INSERT INTO device_pages (device_id,page_id,title,enabled,position,settings)
        SELECT d.id,'finance','Finanzen',0,
        COALESCE((SELECT MAX(p.position) FROM device_pages p WHERE p.device_id=d.id),0)+1,'{}'
        FROM devices d WHERE NOT EXISTS
        (SELECT 1 FROM device_pages p WHERE p.device_id=d.id AND p.page_id='finance')"""))
    op.execute(sa.text("UPDATE devices SET config_version=config_version+1"))


def downgrade():
    op.execute(sa.text("DELETE FROM device_pages WHERE page_id='finance'"))
    op.execute(sa.text("UPDATE devices SET config_version=config_version+1"))
    op.drop_table("finance_cache")
