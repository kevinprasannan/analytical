"""Golden Cross per timeframe (docs/07 §4.19, docs/05 §7).

``GET /instruments/{id}/golden-cross-grid`` — the 50 / 200 SMA cross state and
the last golden / death cross for each of 5m / 15m / 1h / 1D. Pure
`analytical_core.indicators.golden_cross` per timeframe, computed on read, not
persisted, not scored. Descriptive — no signal, no BUY/SELL.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api import services
from app.api.deps import get_db
from app.api.errors import not_found
from app.api.schemas.golden_cross_grid import GoldenCrossGridResponse

router = APIRouter(prefix="/api/v1", tags=["golden-cross-grid"])


@router.get(
    "/instruments/{instrument_id}/golden-cross-grid",
    response_model=GoldenCrossGridResponse,
)
def golden_cross_grid(
    instrument_id: int,
    db: Session = Depends(get_db),
) -> GoldenCrossGridResponse:
    res = services.golden_cross_grid(db, instrument_id)
    if res is None:
        raise not_found("instrument")
    return GoldenCrossGridResponse.model_validate(res)
