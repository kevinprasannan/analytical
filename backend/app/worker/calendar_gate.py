"""Session gate for the scheduled worker loop (docs/02 §3.7).

A scheduled tick only runs a cycle while the NSE session is (nearly) live: from
``scheduler_warmup_seconds`` before open to ``scheduler_cooldown_seconds`` after
close, on a ``market_calendar`` trading day. Outside that window the tick is a
cheap no-op — nothing to ingest, nothing to recompute.

Session bounds come from the same ``market_calendar`` table the API's
``/calendar/status`` reads (``app/api/routers/calendar.py``); the open/close
comparison mirrors that endpoint, plus the warmup/cooldown margins.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import models as m

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True, slots=True)
class GateDecision:
    should_run: bool
    reason: str
    session_open_utc: datetime | None = None
    session_close_utc: datetime | None = None


def evaluate_gate(
    session: Session,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> GateDecision:
    """Decide whether a scheduled cycle should run at ``now`` (tz-aware UTC)."""
    settings = settings or get_settings()
    now = (now or datetime.now(tz=UTC)).astimezone(UTC)

    if not settings.scheduler_session_only:
        return GateDecision(True, "session gating disabled")

    now_ist = now.astimezone(IST)
    row = session.execute(
        select(m.MarketCalendar).where(
            m.MarketCalendar.exchange == "NSE",
            m.MarketCalendar.segment == settings.scheduler_segment,
            m.MarketCalendar.calendar_date == now_ist.date(),
        )
    ).scalar_one_or_none()

    if row is None:
        return GateDecision(False, f"no market_calendar row for {now_ist.date().isoformat()}")
    if not row.is_trading_day:
        return GateDecision(False, f"{now_ist.date().isoformat()} is not a trading day")

    open_ist = datetime.combine(now_ist.date(), row.session_open_ist, tzinfo=IST)
    close_ist = datetime.combine(now_ist.date(), row.session_close_ist, tzinfo=IST)
    open_utc = open_ist.astimezone(UTC)
    close_utc = close_ist.astimezone(UTC)
    window_start = open_utc - timedelta(seconds=settings.scheduler_warmup_seconds)
    window_end = close_utc + timedelta(seconds=settings.scheduler_cooldown_seconds)

    if now < window_start:
        return GateDecision(False, "before session warmup window", open_utc, close_utc)
    if now >= window_end:
        return GateDecision(False, "after session cooldown window", open_utc, close_utc)
    return GateDecision(True, "session live", open_utc, close_utc)
