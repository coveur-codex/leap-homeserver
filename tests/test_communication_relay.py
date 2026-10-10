from datetime import datetime, timedelta, timezone
from sqlalchemy import func, select

from app.models import CommunicationMessage, CommunicationRelayEvent, Device
from app.services.communication import prune_relay
from app.services.devices import initialize_pages


def devices(db):
    for identifier in ("a", "b", "c"):
        d = Device(device_id=identifier, name=f"Device {identifier}", avatar_name=f"Pet {identifier}")
        initialize_pages(d)
        db.add(d)
    db.commit()
    return db.scalars(select(CommunicationMessage).where(CommunicationMessage.active == True)).first().id


def send(client, template, sender="a", event="event-1"):
    return client.post(f"/api/v1/devices/{sender}/communication/messages",
                       json={"templateId": template, "eventId": event})


def receive(client, device="b", since=None):
    return client.get(f"/api/v1/devices/{device}/communication/messages",
                      params={} if since is None else {"since": since})


def test_broadcast_cursor_retry_and_server_owned_snapshot(client, db):
    template = devices(db)
    assert receive(client).json()["cursor"] == 0
    response = send(client, template)
    assert response.status_code == 200
    event = response.json()["message"]
    assert event["senderId"] == "a" and event["name"] == "Pet a"
    assert event["text"] == db.get(CommunicationMessage, template).text
    assert event["symbol"] == db.get(CommunicationMessage, template).symbol
    assert send(client, template).json() == response.json()
    assert db.scalar(select(func.count()).select_from(CommunicationRelayEvent)) == 1
    for recipient in ("a", "b", "c"):
        result = receive(client, recipient, 0).json()
        assert result["messages"] == [event] and result["cursor"] == event["id"]
        assert receive(client, recipient, result["cursor"]).json()["messages"] == []
    # A server restart/template edit cannot mutate the delivered snapshot.
    db.get(CommunicationMessage, template).text = "Changed"
    db.get(CommunicationMessage, template).active = False
    db.scalar(select(Device).where(Device.device_id == "a")).avatar_name = "Changed"
    db.commit()
    db.expire_all()
    assert receive(client).json()["messages"] == [event]
    assert send(client, template).json() == response.json()  # Retry acknowledges original.
    assert send(client, template, event="new").status_code == 422


def test_boot_seed_pagination_restore_and_per_sender_ids(client, db):
    template = devices(db)
    for i in range(19):
        assert send(client, template, event=f"event-{i}").status_code == 200
    initial = receive(client).json()
    assert len(initial["messages"]) == 8 and initial["cursor"] == 19
    assert [m["id"] for m in initial["messages"]] == list(range(12, 20))
    ids, cursor = [], 0
    while True:
        result = receive(client, since=cursor).json()
        ids += [m["id"] for m in result["messages"]]
        cursor = result["cursor"]
        if not result["more"]:
            break
    assert ids == list(range(1, 20))
    restored = receive(client, since=999).json()
    assert restored["reset"] and restored["cursor"] == 19 and len(restored["messages"]) == 8
    assert send(client, template, sender="b", event="event-0").json()["message"]["id"] == 20
    another = db.scalars(select(CommunicationMessage).where(CommunicationMessage.id != template)).first().id
    assert send(client, another, event="event-0").status_code == 409


def test_permissions_and_input_validation(client, db):
    template = devices(db)
    disabled = db.scalar(select(Device).where(Device.device_id == "b"))
    disabled.communication_enabled = False
    db.commit()
    assert receive(client).status_code == 403
    assert send(client, template, sender="b").status_code == 403
    disabled.enabled = False
    db.commit()
    assert receive(client).status_code == 404
    assert send(client, template, sender="b").status_code == 404
    assert send(client, template, sender="unknown").status_code == 404
    assert send(client, "unknown").status_code == 422
    for payload in ({"templateId": template, "eventId": ""},
                    {"templateId": template, "eventId": "x" * 65},
                    {"templateId": template, "eventId": "x", "text": "Injected"},
                    {"templateId": template, "eventId": "x", "name": "Injected"}):
        assert client.post("/api/v1/devices/a/communication/messages", json=payload).status_code == 422
    assert receive(client, "a", -1).status_code == 422


def test_retention_never_reuses_a_cursor(client, db):
    template = devices(db)
    first = send(client, template).json()["message"]["id"]
    event = db.get(CommunicationRelayEvent, first)
    event.sent_at = datetime.now(timezone.utc) - timedelta(days=8)
    db.commit()
    prune_relay(db)
    db.commit()
    assert receive(client, since=first).json()["reset"]
    next_id = send(client, template, event="next").json()["message"]["id"]
    assert next_id > first
