"""Podcast metadata, explicit device grants and per-device playback progress."""
from alembic import op
import sqlalchemy as sa
revision = '0025'
down_revision = '0024'
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    columns = {c['name'] for c in sa.inspect(bind).get_columns('devices')}
    for name, default in [('podcast_ids', '[]'), ('podcast_last', '{}')]:
        if name not in columns:
            op.add_column('devices', sa.Column(name, sa.JSON(), nullable=False, server_default=default))
    tables = set(sa.inspect(bind).get_table_names())
    if 'podcasts' not in tables:
        op.create_table('podcasts', sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('name', sa.String(120), nullable=False), sa.Column('url', sa.String(1000), nullable=False, unique=True),
            sa.Column('enabled', sa.Boolean(), nullable=False), sa.Column('position', sa.Integer(), nullable=False),
            sa.Column('last_fetch', sa.DateTime(timezone=True)), sa.Column('last_success', sa.DateTime(timezone=True)),
            sa.Column('last_error', sa.Text()))
    if 'podcast_episodes' not in tables:
        op.create_table('podcast_episodes', sa.Column('id', sa.String(64), primary_key=True),
            sa.Column('podcast_id', sa.Integer(), sa.ForeignKey('podcasts.id', ondelete='CASCADE'), nullable=False),
            sa.Column('external_id', sa.Text(), nullable=False), sa.Column('title', sa.String(500), nullable=False),
            sa.Column('description', sa.Text(), nullable=False), sa.Column('published_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('duration', sa.Integer()), sa.Column('url', sa.String(1000), nullable=False),
            sa.Column('mime_type', sa.String(100), nullable=False), sa.Column('supported', sa.Boolean(), nullable=False),
            sa.Column('available', sa.Boolean(), nullable=False), sa.UniqueConstraint('podcast_id', 'external_id'))
        op.create_index('ix_podcast_episodes_podcast_id', 'podcast_episodes', ['podcast_id'])
        op.create_index('ix_podcast_episodes_published_at', 'podcast_episodes', ['published_at'])
    if 'podcast_progress' not in tables:
        op.create_table('podcast_progress',
            sa.Column('device_id', sa.Integer(), sa.ForeignKey('devices.id', ondelete='CASCADE'), primary_key=True),
            sa.Column('episode_id', sa.String(64), sa.ForeignKey('podcast_episodes.id', ondelete='CASCADE'), primary_key=True),
            sa.Column('position', sa.Integer(), nullable=False), sa.Column('duration', sa.Integer()),
            sa.Column('status', sa.String(12), nullable=False), sa.Column('revision', sa.BigInteger(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.execute(sa.text("""INSERT INTO device_pages (device_id,page_id,title,enabled,position,settings)
        SELECT d.id,'podcasts','Podcasts',0,
        COALESCE((SELECT MAX(p.position) FROM device_pages p WHERE p.device_id=d.id),0)+1,'{}'
        FROM devices d WHERE NOT EXISTS
        (SELECT 1 FROM device_pages p WHERE p.device_id=d.id AND p.page_id='podcasts')"""))
    op.execute(sa.text('UPDATE devices SET config_version=config_version+1'))

def downgrade():
    op.execute(sa.text("DELETE FROM device_pages WHERE page_id='podcasts'"))
    for name in ['podcast_progress', 'podcast_episodes', 'podcasts']: op.drop_table(name)
    op.drop_column('devices', 'podcast_last')
    op.drop_column('devices', 'podcast_ids')
