"""CPR + classic pivots (docs/07 §4.18, docs/05 §10.13).

``GET /instruments/{id}/pivots`` — the CPR band (TC / pivot / BC) and classic
floor R1-R3 / S1-S3 for the daily, weekly and monthly periods, from the last
completed period's H/L/C, with ~3 months of history and the developing period.
Computed on read from D1 bars, not persisted, not scored. Descriptive — no
bias, no BUY/SELL, no target / stop.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api import services
from app.api.deps import get_db
from app.api.errors import ApiError, not_found
from app.api.schemas.pivots import PivotsResponse

router = APIRouter(prefix="/api/v1", tags=["pivots"])


@router.get("/instruments/{instrument_id}/pivots", response_model=PivotsResponse)
def pivots(
    instrument_id: int,
    daily_history: int = Query(66, ge=1, le=250, description="completed daily periods to return"),
    weekly_history: int = Query(13, ge=1, le=52),
    monthly_history: int = Query(4, ge=1, le=24),
    daily_on: str | None = Query(
        None,
        description="'MM-DD' — switch daily history to the same calendar date, N years back",
    ),
    daily_years: int = Query(20, ge=1, le=40, description="years back for the daily_on view"),
    db: Session = Depends(get_db),
) -> PivotsResponse:
    try:
        res = services.pivots_view(
            db,
            instrument_id,
            daily_history=daily_history,
            weekly_history=weekly_history,
            monthly_history=monthly_history,
            daily_on=daily_on,
            daily_years=daily_years,
        )
    except ValueError as exc:
        raise ApiError(422, "Unprocessable Entity", str(exc)) from exc
    if res is None:
        raise not_found("instrument")
    return PivotsResponse.model_validate(res)
