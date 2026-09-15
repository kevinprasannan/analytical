"""NSE session model + session-anchored timeframe grid (Phase 2.4).

Provider-neutral. This is the single place that knows the NSE 09:15–15:30 IST
continuous session (docs/05 §3.1) and how it divides into the session-anchored
M5 / M15 / H1 grids of docs/05 §3.3 — including the trailing **partial** period
(the 15-minute 15:15–15:30 H1 bar in the default session, and the generic
``floor((close-open)/interval)`` full periods + one partial iff there is a
remainder for a shortened session).

All instants are **bar-open, tz-aware UTC** (docs/03 §2). ``analytical_core``
has its own ``SessionSpec`` (docs/04 §3.1) for the engine side; this module
remains the ingestion-layer source of truth and the two are not yet unified.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from analytical_core.enums import Timeframe

IST = ZoneInfo("Asia/Kolkata")

#: default NSE continuous session (docs/05 §3.1). A shortened `NORMAL` day
#: overrides these from `market_calendar` — the caller passes a different
#: `SessionWindow`; nothing here hard-codes the length.
NSE_SESSION_OPEN_IST = time(9, 15)
NSE_SESSION_CLOSE_IST = time(15, 30)

_INTERVAL: dict[Timeframe, timedelta] = {
    Timeframe.M5: timedelta(minutes=5),
    Timeframe.M15: timedelta(minutes=15),
    Timeframe.H1: timedelta(hours=1),
}

AGGREGATED_TIMEFRAMES: tuple[Timeframe, ...] = (Timeframe.M5, Timeframe.M15, Timeframe.H1)


@dataclass(frozen=True, slots=True)
class SessionWindow:
    """One trading date's continuous session as bar-open UTC bounds ``[open, close)``."""

    trading_date: date
    open_utc: datetime
    close_utc: datetime

    def contains(self, ts: datetime) -> bool:
        return self.open_utc <= ts < self.close_utc


@dataclass(frozen=True, slots=True)
class GridPeriod:
    """One session-anchored period ``[start_utc, end_utc)``.

    ``is_partial`` is ``True`` only for a trailing period shorter than its
    timeframe's nominal interval (docs/05 §3.3 — the 15:15–15:30 H1 bar by
    default). A partial period is still a real bar; it is not fabricated and not
    dropped.
    """

    timeframe: Timeframe
    start_utc: datetime
    end_utc: datetime
    is_partial: bool


def nse_session_window(
    trading_date: date,
    *,
    open_ist: time = NSE_SESSION_OPEN_IST,
    close_ist: time = NSE_SESSION_CLOSE_IST,
) -> SessionWindow:
    open_utc = datetime.combine(trading_date, open_ist, tzinfo=IST).astimezone(UTC)
    close_utc = datetime.combine(trading_date, close_ist, tzinfo=IST).astimezone(UTC)
    if close_utc <= open_utc:
        raise ValueError(f"session close {close_ist} is not after open {open_ist}")
    return SessionWindow(trading_date, open_utc, close_utc)


def trading_date_of(ts: datetime) -> date:
    """The IST calendar date a bar-open UTC timestamp belongs to."""
    if ts.tzinfo is None:
        raise ValueError("timestamp must be tz-aware")
    return ts.astimezone(IST).date()


def session_grid(window: SessionWindow, timeframe: Timeframe) -> list[GridPeriod]:
    """The full ordered list of session-anchored periods for ``timeframe``.

    ``floor(span / interval)`` full periods, then one partial period iff there is
    a non-zero remainder (docs/05 §3.3).
    """
    try:
        interval = _INTERVAL[timeframe]
    except KeyError:
        raise ValueError(
            f"{timeframe.value} is not an aggregated timeframe "
            f"({[t.value for t in AGGREGATED_TIMEFRAMES]})"
        ) from None

    span = window.close_utc - window.open_utc
    full = span // interval  # int number of whole periods
    periods: list[GridPeriod] = []
    for k in range(full):
        start = window.open_utc + k * interval
        periods.append(GridPeriod(timeframe, start, start + interval, is_partial=False))
    if span - full * interval > timedelta(0):
        start = window.open_utc + full * interval
        periods.append(GridPeriod(timeframe, start, window.close_utc, is_partial=True))
    return periods


def expected_grid_len(window: SessionWindow, timeframe: Timeframe) -> int:
    """Session-anchored period count for a coverage-ratio denominator (docs/04 §3.1)."""
    return len(session_grid(window, timeframe))


def group_by_trading_date(timestamps: Iterable[datetime]) -> list[date]:
    """Distinct IST trading dates present, ascending."""
    return sorted({trading_date_of(ts) for ts in timestamps})
