"""Daily digest (docs/07 §4.12).

``GET /instruments/{id}/daily-digest`` — one row per trading day: D1 OHLC, gap /
range %, previous-day-high & previous-day-low break flags, and the day's TPO
profile (shape, day-type, POC / VAH / VAL / IB, close-vs-value) where a
``market_profile_sessions`` row exists. Computed on read; table only, no charts.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api import services
from app.api.deps import get_db
from app.api.errors import ApiError, not_found
from app.api.schemas.daily_digest import DailyDigestResponse

router = APIRouter(prefix="/api/v1", tags=["daily-digest"])


@router.get("/instruments/{instrument_id}/daily-digest", response_model=DailyDigestResponse)
def daily_digest(
    instrument_id: int,
    start: date | None = Query(None, description="ISO date, inclusive"),
    end: date | None = Query(None, description="ISO date, inclusive"),
    sort: str = Query("-d", description="d | change | range | gap; '-' prefix = desc"),
    limit: int = Query(250, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    gap_min_pct: float | None = Query(None, description="keep days with gap_pct >= this"),
    gap_max_pct: float | None = Query(None, description="keep days with gap_pct <= this"),
    chg_min_pct: float | None = Query(None, description="keep days with change_pct >= this"),
    chg_max_pct: float | None = Query(None, description="keep days with change_pct <= this"),
    db: Session = Depends(get_db),
) -> DailyDigestResponse:
    if gap_min_pct is not None and gap_max_pct is not None and gap_min_pct > gap_max_pct:
        raise ApiError(422, "Unprocessable Entity", "gap_min_pct must be <= gap_max_pct")
    if chg_min_pct is not None and chg_max_pct is not None and chg_min_pct > chg_max_pct:
        raise ApiError(422, "Unprocessable Entity", "chg_min_pct must be <= chg_max_pct")
    try:
        res = services.daily_digest(
            db,
            instrument_id,
            start=start,
            end=end,
            sort=sort,
            limit=limit,
            offset=offset,
            gap_min_pct=gap_min_pct,
            gap_max_pct=gap_max_pct,
            chg_min_pct=chg_min_pct,
            chg_max_pct=chg_max_pct,
        )
    except ValueError as exc:
        raise ApiError(422, "Unprocessable Entity", str(exc)) from exc
    if res is None:
        raise not_found("instrument")
    return DailyDigestResponse.model_validate(res)
