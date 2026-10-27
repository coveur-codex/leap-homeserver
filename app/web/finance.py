"""Small per-device symbol editor; order is stored in DevicePage.settings."""
from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models import Device, FinanceCache
from app.services import finance
from app.core.config import settings

router = APIRouter()


def page_for(db, id):
    device = db.get(Device, id)
    if not device:
        raise HTTPException(404, "Gerät nicht gefunden")
    page = next((p for p in device.pages if p.page_id == "finance"), None)
    if not page:
        raise HTTPException(409, "Finanzmigration fehlt; Server aktualisieren")
    return device, page


def save(db, device, page, symbols):
    page.settings = {**(page.settings or {}), "symbols": symbols}
    device.config_version += 1
    db.commit()
    return RedirectResponse(f"/devices/{device.id}#finance", status_code=303)


@router.post("/devices/{id}/finance/add")
async def add(id: int, symbol: str = Form(), db: Session = Depends(get_db)):
    device, page = page_for(db, id)
    try: symbol = finance.normalize_symbol(symbol)
    except ValueError as error: raise HTTPException(422, str(error))
    symbols = finance.symbols_for(device)
    if symbol in symbols:
        return RedirectResponse(f"/devices/{id}#finance", status_code=303)
    if len(symbols) >= finance.MAX_SYMBOLS:
        raise HTTPException(422, f"Maximal {finance.MAX_SYMBOLS} Wertpapiere pro Gerät")
    global_symbols = {s for d in db.query(Device).all() for s in finance.symbols_for(d)}
    if symbol not in global_symbols and len(global_symbols) >= finance.MAX_GLOBAL_SYMBOLS:
        raise HTTPException(422, "Globale Grenze von 256 Wertpapieren erreicht")
    # Keep unsupported entries so the device editor can display a useful error,
    # and a missing key never discards the user's configuration.
    async with finance._lock:
        try: await finance.refresh_symbol(db, symbol)
        except finance.ProviderError: pass
    return save(db, device, page, symbols + [symbol])


@router.post("/devices/{id}/finance/change")
async def change(id: int, symbol: str = Form(), action: str = Form(), db: Session = Depends(get_db)):
    device, page = page_for(db, id)
    symbols = finance.symbols_for(device)
    if symbol not in symbols: raise HTTPException(404, "Symbol nicht konfiguriert")
    if action == "retry":
        async with finance._lock:
            try: await finance.refresh_symbol(db, symbol, force=True)
            except finance.ProviderError as error: raise HTTPException(422, str(error))
        return RedirectResponse(f"/devices/{id}#finance", status_code=303)
    index = symbols.index(symbol)
    if action == "delete": symbols.remove(symbol)
    elif action in {"up", "down"}:
        target = index + (-1 if action == "up" else 1)
        if 0 <= target < len(symbols): symbols[index], symbols[target] = symbols[target], symbols[index]
    else: raise HTTPException(422, "Unbekannte Aktion")
    return save(db, device, page, symbols)
