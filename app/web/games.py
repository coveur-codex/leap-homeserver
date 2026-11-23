"""Async readers stay on the same event loop as game simulations/providers."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import RangierwerkSettings
from app.services.rangierwerk import LEVELS
from app.services.game_status import registry
from app.web.routes import templates

router = APIRouter()
NO_CACHE = {"Cache-Control": "no-store"}


@router.get("/games", response_class=HTMLResponse)
async def games(request: Request):
    return templates.TemplateResponse(request, "game_status.html", {
        "status": registry.snapshot(), "rangierwerk_levels": LEVELS,
        "rangierwerk_level": request.app.state.rangierwerk.next_difficulty,
    }, headers=NO_CACHE)


@router.post("/games/rangierwerk")
async def configure_rangierwerk(request: Request, difficulty: int = Form(ge=1, le=4),
                                 db: Session = Depends(get_db)):
    setting = db.get(RangierwerkSettings, 1)
    if setting is None:
        setting = RangierwerkSettings(id=1)
        db.add(setting)
    setting.difficulty = difficulty
    db.commit()
    request.app.state.rangierwerk.next_difficulty = difficulty
    return RedirectResponse("/games#rangierwerk-settings", status_code=303)


@router.get("/games/status", response_class=HTMLResponse, include_in_schema=False)
async def game_cards(request: Request):
    return templates.TemplateResponse(request, "game_status_cards.html", {"status": registry.snapshot()}, headers=NO_CACHE)


@router.get("/api/v1/games/status")
async def game_status():
    return JSONResponse(registry.snapshot(), headers=NO_CACHE)
