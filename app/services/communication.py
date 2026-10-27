"""Global message templates published through the existing asset lifecycle."""
import json
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from app.models import AssetPackage, CommunicationMessage
from app.services import distribution

PACKAGE_ID = "communication-messages"


def messages(db):
    return db.scalars(select(CommunicationMessage).order_by(CommunicationMessage.position, CommunicationMessage.id)).all()


def active_messages(db):
    return [message for message in messages(db) if message.active]


def publish(db, package, expected):
    db.flush()
    rows = [{"id": m.id, "text": m.text, "symbol": m.symbol, "order": m.position} for m in active_messages(db)]
    data = json.dumps({"schemaVersion": 1, "messages": rows}, ensure_ascii=False).encode()
    return distribution.publish(db, package, {"messages.json": distribution.store_bytes(data)},
                                {"messagesFile": "messages.json", "messageCount": len(rows)}, expected)


def ensure_package(db):
    if db.get(AssetPackage, PACKAGE_ID):
        return False
    package = AssetPackage(id=PACKAGE_ID, kind="communication", name="Kommunikation", current_version=0)
    db.add(package)
    # Seed once only. Deleting all messages must keep the list empty on restart.
    if not db.scalar(select(CommunicationMessage.id).limit(1)):
        defaults = json.loads((Path(__file__).resolve().parents[1] / "defaults/communication-messages.json").read_text())
        for position, row in enumerate(defaults, 1):
            db.add(CommunicationMessage(id=str(uuid4()), text=row["text"], symbol=row.get("symbol", ""), position=position, active=True))
    db.flush()
    publish(db, package, 0)
    return True


def prune_relay(db):
    """Bound the shared history; SQLite AUTOINCREMENT never reuses cursors."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import delete
    from app.models import CommunicationRelayEvent
    db.execute(delete(CommunicationRelayEvent).where(
        CommunicationRelayEvent.sent_at < datetime.now(timezone.utc) - timedelta(days=7)))
