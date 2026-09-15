"""Trading calendar (docs/07 §4.8)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api import services
from app.api.deps import get_db
from app.api.errors import ApiError

router = APIRouter(prefix="/api/v1/calendar", tags=["calendar"])
IST = ZoneInfo("Asia/Kolkata")


def _row(r) -> dict[str, Any]:
    return {
        "calendar_date": r.calendar_date.isoformat(),
        "is_trading_day": r.is_trading_day,
        "session_open_ist": r.session_open_ist.strftime("%H:%M"),
        "session_close_ist": r.session_close_ist.strftime("%H:%M"),
        "session_type": r.session_type,
        "segment": r.segment,
        "exchange": r.exchange,
        "note": r.note,
    }


@router.get("")
def calendar(
    start: date,
    end: date,
    db: Session = Depends(get_db),
    segment: str = "FO",
) -> dict[str, Any]:
    if (end - start).days > 400:
        raise ApiError(422, "Unprocessable Entity", "range exceeds 400 days")
    rows = services.calendar_rows(db, start, end, segment=segment)
    return {"start": start.isoformat(), "end": end.isoformat(), "days": [_row(r) for r in rows]}


@router.get("/status")
def status(
    db: Session = Depends(get_db),
    now: datetime | None = Query(None, description="override 'now' (testing)"),
    segment: str = "FO",
) -> dict[str, Any]:
    now = (now or datetime.now(tz=UTC)).astimezone(UTC)
    now_ist = now.astimezone(IST)
    today = services.calendar_row_for(db, now_ist.date(), segment=segment)

    open_now = False
    next_open_ist: datetime | None = None
    next_close_ist: datetime | None = None
    if today is not None and today.is_trading_day:
        o = datetime.combine(now_ist.date(), today.session_open_ist, tzinfo=IST)
        c = datetime.combine(now_ist.date(), today.session_close_ist, tzinfo=IST)
        if o <= now_ist < c:
            open_now = True
            next_close_ist = c
        elif now_ist < o:
            next_open_ist = o
    if next_open_ist is None and not open_now:
        nxt = services.next_trading_day_row(db, now_ist.date() + timedelta(days=1), segment=segment)
        if nxt is not None:
            next_open_ist = datetime.combine(nxt.calendar_date, nxt.session_open_ist, tzinfo=IST)

    seeded = services.calendar_seeded_until(db, segment=segment)

    def _pair(dt: datetime | None) -> dict[str, str] | None:
        return (
            None if dt is None else {"ist": dt.isoformat(), "utc": dt.astimezone(UTC).isoformat()}
        )

    return {
        "is_open": open_now,
        "as_of": {"ist": now_ist.isoformat(), "utc": now.isoformat()},
        "session_type": today.session_type if today else None,
        "next_open": _pair(next_open_ist),
        "next_close": _pair(next_close_ist),
        "seeded_until": seeded.isoformat() if seeded else None,
    }
