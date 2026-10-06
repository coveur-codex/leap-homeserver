from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.routes import device_or_404
from app.core.database import get_db
from app.models import QuizAttempt

router = APIRouter(prefix="/api/v1/devices/{device_id}/quiz-attempts")


class Attempt(BaseModel):
    eventId: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9-]+$")
    kind: Literal["catalog", "math"]
    quizSetId: str = Field(min_length=1, max_length=120)
    quizSetName: str = Field(min_length=1, max_length=240)
    quizSetVersion: int | None = Field(None, ge=0)
    questionId: str | int | None = None
    questionIndex: int = Field(ge=0)
    question: str = Field(min_length=1, max_length=10000)
    answers: list[Annotated[str, Field(max_length=524288)]] = Field(min_length=4, max_length=4)
    selectedIndex: int = Field(ge=0, le=3)
    correctIndex: int = Field(ge=0, le=3)
    elapsedMs: int | None = Field(None, ge=0, le=4294967295)
    answeredAt: datetime | None = None
    firmwareVersion: str = Field(max_length=40)
    mathOperation: Literal["add", "subtract", "multiply"] | None = None
    mathLimit: int | None = Field(None, ge=3, le=1000)

    @model_validator(mode="after")
    def validate_snapshot(self):
        if isinstance(self.questionId, str) and len(self.questionId) > 120:
            raise ValueError("Question ID too long")
        if self.answeredAt is not None and self.answeredAt.utcoffset() is None:
            raise ValueError("answeredAt requires a timezone")
        if self.kind == "math" and (self.mathOperation is None or self.mathLimit is None):
            raise ValueError("Math settings are required")
        if self.mathOperation == "multiply" and self.mathLimit is not None and self.mathLimit > 20:
            raise ValueError("Multiplication limit exceeds 20")
        return self


def serialize_attempt(row):
    return {**row.snapshot, "correct": row.correct, "receivedAt": row.received_at}


@router.post("")
def record(device_id: str, data: Attempt, db: Session = Depends(get_db)):
    device = device_or_404(device_id, db)
    snapshot = data.model_dump(mode="json")
    existing = db.scalar(select(QuizAttempt).where(
        QuizAttempt.device_id == device.id, QuizAttempt.event_id == data.eventId))
    if existing:
        if existing.snapshot != snapshot:
            raise HTTPException(409, "Ereignis-ID bereits mit anderer Antwort gespeichert")
        return {"ok": True, "eventId": data.eventId}
    db.add(QuizAttempt(device_id=device.id, event_id=data.eventId, snapshot=snapshot,
                       correct=data.selectedIndex == data.correctIndex))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # A concurrent retry may have stored the same immutable event.
        existing = db.scalar(select(QuizAttempt).where(
            QuizAttempt.device_id == device.id, QuizAttempt.event_id == data.eventId))
        if not existing or existing.snapshot != snapshot:
            raise HTTPException(409, "Ereignis-ID bereits vergeben")
    return {"ok": True, "eventId": data.eventId}


@router.get("")
def history(device_id: str, limit: int = Query(50, ge=1, le=100),
            offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    device = device_or_404(device_id, db)
    rows = db.scalars(select(QuizAttempt).where(QuizAttempt.device_id == device.id)
                      .order_by(QuizAttempt.id.desc()).offset(offset).limit(limit + 1)).all()
    return {"attempts": [serialize_attempt(row) for row in rows[:limit]],
            "hasMore": len(rows) > limit}
