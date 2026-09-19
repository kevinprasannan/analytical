"""Economic event calendar (docs/07 §4.27, docs/05 §9g).

``GET /instruments/{id}/event-calendar`` — a small set of recurring-date
event types (not live news): US jobs report, India GST collection, monthly
F&O expiry (current/next only, no historical backfill), each with a
before/after price read on the instrument being viewed. Pure math
(`analytical_core.event_calendar`), computed on read, not persisted, not
scored. Descriptive — no signal, no BUY/SELL.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api import services
from app.api.deps import get_db
from app.api.errors import not_found
from app.api.schemas.event_calendar import EventCalendarResponse

router = APIRouter(prefix="/api/v1", tags=["event-calendar"])


@router.get("/instruments/{instrument_id}/event-calendar", response_model=EventCalendarResponse)
def event_calendar(
    instrument_id: int,
    notable_move_pct: float = Query(0.5, ge=0, description="|change_pct| >= this is 'notable'"),
    future_horizon_months: int = Query(2, ge=0, le=12),
    db: Session = Depends(get_db),
) -> EventCalendarResponse:
    res = services.event_calendar(
        db,
        instrument_id,
        notable_move_pct=notable_move_pct,
        future_horizon_months=future_horizon_months,
    )
    if res is None:
        raise not_found("instrument")
    return EventCalendarResponse.model_validate(res)
