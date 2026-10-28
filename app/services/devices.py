from app.services.room import default_config, DEFAULT_ROOMS
from app.core.pages import PAGE_REGISTRY
from app.models import Device, DevicePage

def initialize_pages(device: Device):
    device.pages = []
    for position, page in enumerate(PAGE_REGISTRY, 1):
        enabled = page.id in {"home", "news", "weather", "quiz", "games", "communication", "time"}
        if page.id == "communication":
            enabled = device.communication_enabled is not False
        elif page.id == "room":
            enabled = device.device_id in DEFAULT_ROOMS
        device.pages.append(DevicePage(
            page_id=page.id, title=page.title, enabled=enabled, position=position,
            settings=default_config(device.device_id) if page.id == "room" else {}))

def page_enabled(device, page):
    return device.communication_enabled if page.page_id == "communication" else page.enabled

def bump_config(device:Device): device.config_version+=1
