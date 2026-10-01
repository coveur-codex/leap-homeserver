from app.core.pages import PAGE_REGISTRY
from app.models import Device, DevicePage

def initialize_pages(device:Device):
    device.pages=[DevicePage(page_id=p.id,title=p.title,enabled=(device.communication_enabled is not False) if p.id == "communication" else p.id in {"home","news","weather","quiz","games","communication"},position=i+1) for i,p in enumerate(PAGE_REGISTRY)]
def page_enabled(device, page):
    return device.communication_enabled if page.page_id == "communication" else page.enabled

def bump_config(device:Device): device.config_version+=1
