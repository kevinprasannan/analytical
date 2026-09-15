"""ICT swing Fair Value Gaps per timeframe (docs/07 §4.21, docs/05 §9c).

``GET /instruments/{id}/fvg-grid`` — the 'left-side' FVGs that form into a swing
high / low and act as inversion arrays, for each of 5m / 15m / 30m / 1h. Pure
scan (`analytical_core.fvg`), computed on read, not persisted, not scored.
Descriptive — no signal, no BUY/SELL.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api import services
from app.api.deps import get_db
from app.api.errors import not_found
from app.api.schemas.fvg_grid import FvgGridResponse

router = APIRouter(prefix="/api/v1", tags=["fvg-grid"])


@router.get("/instruments/{instrument_id}/fvg-grid", response_model=FvgGridResponse)
def fvg_grid(instrument_id: int, db: Session = Depends(get_db)) -> FvgGridResponse:
    res = services.fvg_grid(db, instrument_id)
    if res is None:
        raise not_found("instrument")
    return FvgGridResponse.model_validate(res)
