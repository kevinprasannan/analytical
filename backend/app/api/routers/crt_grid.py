"""Candle Range Theory per timeframe (docs/07 §4.24, docs/05 §9d).

``GET /instruments/{id}/crt-grid`` — a reference candle's High-Low range and
how price has behaved around it since (accepted / rejected / expanded), for
each of 5m / 15m / 30m / 1h. Pure scan (`analytical_core.crt`), computed on
read, not persisted, not scored. Descriptive — no signal, no BUY/SELL.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api import services
from app.api.deps import get_db
from app.api.errors import not_found
from app.api.schemas.crt_grid import CrtGridResponse

router = APIRouter(prefix="/api/v1", tags=["crt-grid"])


@router.get("/instruments/{instrument_id}/crt-grid", response_model=CrtGridResponse)
def crt_grid(instrument_id: int, db: Session = Depends(get_db)) -> CrtGridResponse:
    res = services.crt_grid(db, instrument_id)
    if res is None:
        raise not_found("instrument")
    return CrtGridResponse.model_validate(res)
