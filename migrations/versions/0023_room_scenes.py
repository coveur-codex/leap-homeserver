"""Add optional per-light scenes and the requested Anna light-chain scene."""
from alembic import op
import sqlalchemy as sa

revision = "0023"
down_revision = "0022"
branch_labels = depends_on = None


def update_pages(remove=False):
    bind = op.get_bind()
    pages = sa.table("device_pages", sa.column("id"), sa.column("device_id"),
                     sa.column("page_id"), sa.column("settings", sa.JSON))
    devices = sa.table("devices", sa.column("id"), sa.column("device_id"), sa.column("config_version"))
    rows = bind.execute(sa.select(pages.c.id, pages.c.device_id, pages.c.settings, devices.c.device_id)
                        .join(devices, pages.c.device_id == devices.c.id).where(pages.c.page_id == "room")).all()
    for pid, did, settings, name in rows:
        if not isinstance(settings, dict):
            continue
        value = dict(settings)
        if remove:
            value.pop("light_scenes", None)
        else:
            scenes = dict(value.get("light_scenes", {}))
            if name == "leap-anna" and "light.lichterkette_anna" in value.get("lights", []):
                scenes.setdefault("light.lichterkette_anna", "scene.anna_lichterkette_szene")
            value["light_scenes"] = scenes
        if value == settings:
            continue
        bind.execute(pages.update().where(pages.c.id == pid).values(settings=value))
        bind.execute(devices.update().where(devices.c.id == did).values(config_version=devices.c.config_version + 1))


def upgrade():
    update_pages()


def downgrade():
    update_pages(remove=True)
