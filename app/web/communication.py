from uuid import uuid4

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models import AssetPackage, CommunicationMessage
from app.services import communication, distribution
from app.web.routes import templates, redir

router = APIRouter()


@router.get("/communication")
def editor(request: Request, db: Session = Depends(get_db)):
    distribution.ensure_packages(db)
    return templates.TemplateResponse(request, "communication.html", {
        "messages": communication.messages(db), "package": db.get(AssetPackage, communication.PACKAGE_ID)})


@router.post("/communication/messages")
def save_message(expected: int = Form(), message_id: str = Form(""), text: str = Form(max_length=120),
                 symbol: str = Form("", max_length=16), position: int = Form(1, ge=1, le=10000),
                 active: bool = Form(False), db: Session = Depends(get_db)):
    if not text.strip():
        raise HTTPException(422, "Nachrichtentext darf nicht leer sein")
    package = db.get(AssetPackage, communication.PACKAGE_ID)
    if not package:
        raise HTTPException(409, "Bitte Kommunikationsseite neu laden")
    message = db.get(CommunicationMessage, message_id) if message_id else CommunicationMessage(id=str(uuid4()))
    if message is None:
        raise HTTPException(404, "Nachricht nicht gefunden")
    message.text, message.symbol, message.position, message.active = text.strip(), symbol.strip(), position, active
    db.add(message)
    try:
        communication.publish(db, package, expected)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return redir("/communication")


@router.post("/communication/messages/{message_id}/delete")
def delete_message(message_id: str, expected: int = Form(), db: Session = Depends(get_db)):
    message = db.get(CommunicationMessage, message_id)
    if message is None:
        raise HTTPException(404, "Nachricht nicht gefunden")
    package = db.get(AssetPackage, communication.PACKAGE_ID)
    db.delete(message)
    try:
        communication.publish(db, package, expected)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return redir("/communication")
