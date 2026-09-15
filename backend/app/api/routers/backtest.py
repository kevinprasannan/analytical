"""Backtesting (docs/07 §4.15, docs/16).

``GET /instruments/{index_id}/backtest/orb`` — opening-range breakout study:
the high/low of a range window, the first breakout of a later window, and
whether price then reached a multiple of the range before the opposite edge.
Configurable windows + target multiples; runs over stored M1 / M15 index bars.

Descriptive research — no signal, no label, no BUY/SELL. Computed on read, not
persisted.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api import services
from app.api.deps import get_db
from app.api.errors import ApiError, not_found
from app.api.schemas.backtest import OrbBacktestResponse

router = APIRouter(prefix="/api/v1", tags=["backtest"])


@router.get("/instruments/{index_id}/backtest/orb", response_model=OrbBacktestResponse)
def backtest_orb(
    index_id: int,
    start: date | None = Query(None, description="ISO date, inclusive (default: end − 365d)"),
    end: date | None = Query(None, description="ISO date, inclusive (default: today)"),
    range_start: str = Query("09:40", description="range window open, IST HH:MM"),
    range_end: str = Query("09:55", description="range window close, IST HH:MM (exclusive)"),
    break_start: str = Query("09:55", description="breakout window open, IST HH:MM"),
    break_end: str = Query("10:15", description="breakout window close, IST HH:MM"),
    measure_until: str | None = Query(
        None, description="measure the outcome until this IST HH:MM (default: break_end)"
    ),
    targets: str = Query("0.5,1.0", description="comma list of range multiples to test"),
    timeframe: str = Query("M1", description="bar granularity: M1 | M15"),
    db: Session = Depends(get_db),
) -> OrbBacktestResponse:
    if services.get_instrument(db, index_id) is None:
        raise not_found("instrument")
    e = end or date.today()
    s = start or (e - timedelta(days=365))
    try:
        res = services.orb_backtest(
            db,
            index_id,
            start=s,
            end=e,
            range_start=range_start,
            range_end=range_end,
            break_start=break_start,
            break_end=break_end,
            measure_until=measure_until,
            targets=targets,
            timeframe=timeframe,
        )
    except ValueError as exc:
        raise ApiError(422, "Unprocessable Entity", str(exc)) from exc
    if res is None:
        raise not_found("index backtest (not an INDEX instrument)")
    return OrbBacktestResponse.model_validate(res)
