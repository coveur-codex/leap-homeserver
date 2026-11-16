from bs4 import BeautifulSoup
import pytest

from app.models import Device
from app.services.devices import initialize_pages


def make_device(db):
    device = Device(device_id="editor-test", name="Editor", age=9, avatar="dragon")
    initialize_pages(device)
    db.add(device)
    db.commit()
    return device


def form(device, **fields):
    return {"name": device.name, "age": device.age, "avatar": device.avatar,
            "enabled": "on", "communication_enabled": "on", **fields}


def test_order_round_trip_keeps_disabled_pages_and_communication(client, db):
    device = make_device(db)
    order = ["room", "communication", "news"] + [
        page.page_id for page in reversed(device.pages)
        if page.page_id not in {"room", "communication", "news"}]
    version = device.config_version
    response = client.post(f"/devices/{device.id}", data=form(
        device, page_ids=["home", "news"], page_order_ids=order), follow_redirects=False)
    assert response.status_code == 303
    db.expire_all()
    assert device.config_version == version + 1
    assert [page.page_id for page in sorted(device.pages, key=lambda p: p.position)] == order
    assert not next(page for page in device.pages if page.page_id == "room").enabled
    assert next(page for page in device.pages if page.page_id == "communication").enabled
    soup = BeautifulSoup(client.get(f"/devices/{device.id}").text, "html.parser")
    assert [item["value"] for item in soup.select('[name="page_order_ids"]')] == order
    assert [page["id"] for page in client.get(
        f"/api/v1/devices/{device.device_id}/config").json()["pages"]] == order
    # Saving a second time uses the displayed IDs, independent of relationship order.
    order.reverse()
    assert client.post(f"/devices/{device.id}", data=form(
        device, page_ids=["home"], page_order_ids=order), follow_redirects=False).status_code == 303
    db.expire_all()
    assert [page.page_id for page in sorted(device.pages, key=lambda p: p.position)] == order


def test_legacy_checkbox_order_still_supported(client, db):
    device = make_device(db)
    response = client.post(f"/devices/{device.id}", data=form(
        device, page_ids=["news", "home"]), follow_redirects=False)
    assert response.status_code == 303
    db.expire_all()
    assert next(page for page in device.pages if page.page_id == "news").position == 1
    assert next(page for page in device.pages if page.page_id == "home").position == 2


@pytest.mark.parametrize("invalid", ["duplicate", "missing", "unknown"])
def test_invalid_order_rejected_before_changes(client, db, invalid):
    device = make_device(db)
    order = [page.page_id for page in device.pages]
    original = order[:]
    if invalid == "duplicate":
        order[-1] = order[0]
    elif invalid == "missing":
        order.pop()
    else:
        order[-1] = "unknown"
    version = device.config_version
    response = client.post(f"/devices/{device.id}", data=form(
        device, name="Changed", page_ids=["news"], page_order_ids=order))
    assert response.status_code == 422
    db.expire_all()
    assert device.name == "Editor" and device.config_version == version
    assert [page.page_id for page in device.pages] == original


def test_editor_layout_and_independent_form_owners(client, db):
    device = make_device(db)
    device.network_config = {"wifiProfiles": [{"ssid": "First", "password": "secret-pass"},
                                             {"ssid": "Second", "password": "other-pass"}]}
    db.commit()
    soup = BeautifulSoup(client.get(f"/devices/{device.id}").text, "html.parser")
    editor = soup.select_one("#device-editor-form")
    assert editor.select_one("form") is None  # Nested forms break browser submission ownership.
    assert len(soup.select('[data-page-handle]')) == len(device.pages)
    assert len(soup.select('[name="page_order_ids"]')) == len(device.pages)
    assert len(editor.select(".device-settings > section")) == 2
    assert editor.select_one('[data-page-panel="room"] [name="climate"]')
    assert editor.select_one('[data-page-panel="games"] #math-lab [name="targets"]')
    assert [section.get("id") for section in editor.select(".device-maintenance > section")] == [
        "firmware-settings", "network", "sync-status"]
    assert editor.select_one(".device-display-preview").find_next_sibling()["class"] == ["device-maintenance"]
    for panel, owner in [("room", "room-settings"), ("games", "math-lab-settings")]:
        for control in editor.select(f'[data-page-panel="{panel}"] [form="{owner}"]'):
            assert soup.select_one(f'form#{control["form"]}')["method"] == "post"
    assert editor.select_one('[name="climate"]')["form"] == "room-settings"
    assert editor.select_one('[name="targets"]')["form"] == "math-lab-settings"
    assert editor.select_one('[name="server"]')["form"] == "network-server"
    assert editor.select_one('[name="password"]')["form"] == "network-wifi"
    removals = editor.select('#network input[type="hidden"][name="ssid"]')
    assert [item["form"] for item in removals] == ["network-remove-1", "network-remove-2"]
    assert "secret-pass" not in str(soup) and "other-pass" not in str(soup)
    ids = [element["id"] for element in soup.select("[id]")]
    assert len(ids) == len(set(ids))
