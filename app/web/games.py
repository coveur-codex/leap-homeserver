"""Async readers stay on the same event loop as game simulations/providers."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from app.services.game_status import registry
from app.web.routes import templates

router = APIRouter()
NO_CACHE = {"Cache-Control": "no-store"}


@router.get("/games", response_class=HTMLResponse)
async def games(request: Request):
    return templates.TemplateResponse(request, "game_status.html", {"status": registry.snapshot()}, headers=NO_CACHE)


@router.get("/games/status", response_class=HTMLResponse, include_in_schema=False)
async def game_cards(request: Request):
    return templates.TemplateResponse(request, "game_status_cards.html", {"status": registry.snapshot()}, headers=NO_CACHE)


@router.get("/api/v1/games/status")
async def game_status():
    return JSONResponse(registry.snapshot(), headers=NO_CACHE)
