"""Key levels (docs/07 §4.16, docs/05 §10.12).

``GET /instruments/{id}/key-levels`` — POC / VAH / VAL / IB / session high-low
from the previous **two completed sessions**, price-sorted, each tagged with
signed distance from the latest price and a proximity tier (AT / NEAR /
APPROACHING / FAR — bands default per instrument, overridable), plus an
acceptance / rejection read from the recent M5 bars. Descriptive — no bias,
no BUY/SELL.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api import services
from app.api.deps import get_db
from app.api.errors import ApiError, not_found
from app.api.schemas.key_levels import KeyLevelsResponse

router = APIRouter(prefix="/api/v1", tags=["key-levels"])


@router.get("/instruments/{instrument_id}/key-levels", response_model=KeyLevelsResponse)
def key_levels(
    instrument_id: int,
    at: float | None = Query(None, gt=0, description="tightest proximity band, points"),
    near: float | None = Query(None, gt=0, description="mid band, points"),
    approaching: float | None = Query(None, gt=0, description="widest band, points"),
    db: Session = Depends(get_db),
) -> KeyLevelsResponse:
    bands = None
    if at is not None or near is not None or approaching is not None:
        if None in (at, near, approaching):
            raise ApiError(422, "Unprocessable Entity", "pass all of at / near / approaching or none")
        bands = (at, near, approaching)
    try:
        res = services.key_levels(db, instrument_id, bands=bands)
    except ValueError as exc:
        raise ApiError(422, "Unprocessable Entity", str(exc)) from exc
    if res is None:
        raise not_found(
            "instrument, or no completed TPO market-profile session for it yet"
        )
    return KeyLevelsResponse.model_validate(res)
