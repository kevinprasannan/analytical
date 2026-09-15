"""Multi-timeframe candle-pattern grid (docs/07 §4.17, docs/05 §9b).

``GET /instruments/{id}/candles-grid`` — the last ``limit`` major candlestick
patterns on each of 5m / 15m / 30m / 1h, newest first. M30 is folded on read
from M5 (no M30 in the engine grid, decision 4). Computed on read, not
persisted, not scored. Descriptive — no bias score, no BUY/SELL.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api import services
from app.api.deps import get_db
from app.api.errors import not_found
from app.api.schemas.candles_grid import CandlesGridResponse

router = APIRouter(prefix="/api/v1", tags=["candles-grid"])


@router.get("/instruments/{instrument_id}/candles-grid", response_model=CandlesGridResponse)
def candles_grid(
    instrument_id: int,
    limit: int = Query(5, ge=1, le=20, description="pattern hits per timeframe column"),
    db: Session = Depends(get_db),
) -> CandlesGridResponse:
    res = services.candles_grid(db, instrument_id, limit=limit)
    if res is None:
        raise not_found("instrument")
    return CandlesGridResponse.model_validate(res)
