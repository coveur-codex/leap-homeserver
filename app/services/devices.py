from app.core.pages import PAGE_REGISTRY
from app.models import Device, DevicePage

def initialize_pages(device:Device):
    device.pages=[DevicePage(page_id=p.id,title=p.title,enabled=p.id in {"home","news","weather","quiz","games"},position=i+1) for i,p in enumerate(PAGE_REGISTRY)]
def bump_config(device:Device): device.config_version+=1
