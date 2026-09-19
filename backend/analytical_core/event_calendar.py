"""Economic event calendar — a small set of recurring-date event types (not
live news) with a historical before/after price read on the instrument
being viewed.

Pure and deterministic. Seven event types are generated purely from calendar
rules, no external data: **US_JOBS_REPORT** (first Friday of each month),
**US_JOBLESS_CLAIMS** (every Thursday — a genuine weekly formula, no
approximation needed), **INDIA_GST_COLLECTION** (nearest trading day
on/after the 1st of each month, GST having launched 2017-07-01 — no
occurrences generated before that), **MCX_GOLD_EXPIRY** / **MCX_SILVER_EXPIRY**
(MCX contract expiry — the 5th calendar day of the month, snapped
*backward* to the nearest earlier trading day when that date isn't one —
approximate: this system has no MCX holiday calendar, so NSE's own trading
days stand in for it, which mostly but not always agree, though MCX and NSE
being both Indian exchanges keeps this reasonably close), and
**COMEX_GOLD_EXPIRY** / **COMEX_SILVER_EXPIRY** (COMEX contract expiry —
approximated as the 27th calendar day of the month, snapped backward to the
nearest earlier NSE trading day — a rougher approximation than the MCX pair,
since COMEX (US) and NSE (India) don't share a holiday calendar at all, only
the day-of-month anchor is a rule-of-thumb stand-in for "a few business days
before month end"). Four more, **FNO_EXPIRY**, **FED_RATE_DECISION**,
**ECB_RATE_DECISION**, and **RBI_RATE_DECISION**, take their dates as input
rather than generating them: FNO_EXPIRY from the tracked option/future
universe (NSE's expiry weekday convention has changed over the years and
this system's instrument table only retains the current/next contract — no
historical backfill attempted); FED_RATE_DECISION/ECB_RATE_DECISION/
RBI_RATE_DECISION from small owner-maintained seed lists (committee-set
dates, not a formula — no rule can generate them, and any list is only as
complete/accurate as whoever last updated it).

For every occurrence that falls within the loaded daily series, records the
prior close, that day's close, and the next day's close, so the actual
price move around the date reads directly off real data. Most occurrences
of any of these event types pass without a large move; the summary's
``pct_notable_move`` is exactly that base rate — the real historical
frequency of a move beyond ``notable_move_pct``, not an assumption. Not a
signal, not a trade recommendation, no entry/target/stop.
"""

from __future__ import annotations

import bisect
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import mean, median
from typing import Any

EVENT_CALENDAR_VERSION = "0.1.0"

DEFAULTS: dict[str, Any] = {
    "notable_move_pct": 0.5,  # |change_pct| >= this counts as a "notable" move
    "gst_start_date": "2017-07-01",  # India GST launched here — no events generated before
    "future_horizon_months": 2,  # also list upcoming event dates this far past the last bar
}

US_JOBS_REPORT = "US_JOBS_REPORT"
US_JOBLESS_CLAIMS = "US_JOBLESS_CLAIMS"
INDIA_GST_COLLECTION = "INDIA_GST_COLLECTION"
FNO_EXPIRY = "FNO_EXPIRY"
MCX_GOLD_EXPIRY = "MCX_GOLD_EXPIRY"
MCX_SILVER_EXPIRY = "MCX_SILVER_EXPIRY"
COMEX_GOLD_EXPIRY = "COMEX_GOLD_EXPIRY"
COMEX_SILVER_EXPIRY = "COMEX_SILVER_EXPIRY"
FED_RATE_DECISION = "FED_RATE_DECISION"
ECB_RATE_DECISION = "ECB_RATE_DECISION"
RBI_RATE_DECISION = "RBI_RATE_DECISION"

_ALL_EVENT_TYPES = (
    US_JOBS_REPORT,
    US_JOBLESS_CLAIMS,
    INDIA_GST_COLLECTION,
    FNO_EXPIRY,
    MCX_GOLD_EXPIRY,
    MCX_SILVER_EXPIRY,
    COMEX_GOLD_EXPIRY,
    COMEX_SILVER_EXPIRY,
    FED_RATE_DECISION,
    ECB_RATE_DECISION,
    RBI_RATE_DECISION,
)


@dataclass(frozen=True, slots=True)
class EventOccurrence:
    event_type: str
    event_date: str
    prior_close: float | None = None
    close: float | None = None
    change_pct: float | None = None  # close vs prior_close
    next_close: float | None = None
    next_change_pct: float | None = None  # next_close vs close


@dataclass(frozen=True, slots=True)
class EventTypeSummary:
    event_type: str
    n_occurrences: int
    n_resolved: int  # occurrences with real price data (excludes future/out-of-range dates)
    mean_abs_change_pct: float | None = None
    median_abs_change_pct: float | None = None
    pct_notable_move: float | None = None
    up_count: int = 0
    down_count: int = 0


@dataclass(frozen=True, slots=True)
class EventCalendarResult:
    status: str  # OK | INSUFFICIENT_DATA
    reason: str | None
    notable_move_pct: float
    summaries: list[EventTypeSummary] = field(default_factory=list)
    occurrences: list[EventOccurrence] = field(default_factory=list)
    event_calendar_version: str = EVENT_CALENDAR_VERSION


def _month_range(start: date, end: date) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def _first_friday(year: int, month: int) -> date:
    d = date(year, month, 1)
    return d + timedelta(days=(4 - d.weekday()) % 7)  # Monday=0 ... Friday=4


def _thursdays(start: date, end: date) -> list[date]:
    d = start + timedelta(days=(3 - start.weekday()) % 7)  # first Thursday >= start
    out: list[date] = []
    while d <= end:
        out.append(d)
        d += timedelta(days=7)
    return out


def scan_event_calendar(
    dates: Sequence[str],
    closes: Sequence[float],
    *,
    fno_expiry_dates: Sequence[str] = (),
    fomc_dates: Sequence[str] = (),
    ecb_dates: Sequence[str] = (),
    rbi_dates: Sequence[str] = (),
    params: Mapping[str, Any] | None = None,
) -> EventCalendarResult:
    """``dates``/``closes`` chronological daily bars, same length, ``dates``
    as ISO ``YYYY-MM-DD`` strings. ``fno_expiry_dates``/``fomc_dates``/
    ``ecb_dates``/``rbi_dates`` are supplied separately (not generated) —
    whatever dates are actually known, past or upcoming."""
    p = {**DEFAULTS, **(params or {})}
    notable = float(p["notable_move_pct"])
    gst_start = date.fromisoformat(str(p["gst_start_date"]))
    horizon_months = int(p["future_horizon_months"])

    n = len(dates)
    if n < 2:
        return EventCalendarResult(
            status="INSUFFICIENT_DATA",
            reason=f"need >= 2 daily bars, have {n}",
            notable_move_pct=notable,
        )

    first_d = date.fromisoformat(dates[0])
    last_d = date.fromisoformat(dates[-1])
    horizon_end = date(last_d.year, last_d.month, 1)  # 1st of the horizon's last month
    for _ in range(horizon_months):
        horizon_end = date(
            horizon_end.year + (1 if horizon_end.month == 12 else 0),
            1 if horizon_end.month == 12 else horizon_end.month + 1,
            1,
        )
    # day-level end bound (last day of horizon_end's month) for the weekly
    # generator — _month_range/candidates below work at month granularity so
    # horizon_end's exact day doesn't matter to them, but a day-by-day walk
    # (Thursdays) needs the real end of that month or it under-covers it
    _next_month = date(
        horizon_end.year + (1 if horizon_end.month == 12 else 0),
        1 if horizon_end.month == 12 else horizon_end.month + 1,
        1,
    )
    horizon_end_day = _next_month - timedelta(days=1)

    def _snap(target: date) -> str | None:
        """Nearest trading date on/after ``target`` within ``dates`` — or
        the ISO date itself, unresolved, if it's past the loaded series
        (still lets a future event show on the calendar with no price yet)."""
        iso = target.isoformat()
        idx = bisect.bisect_left(dates, iso)
        if idx < n:
            return dates[idx]
        return None

    def _snap_back(target: date) -> str | None:
        """Nearest trading date on/before ``target`` within ``dates`` — or
        None if target is beyond the loaded series (can't resolve a future
        date against real trading days yet, same convention as ``_snap``)."""
        if target > last_d:
            return None
        idx = bisect.bisect_right(dates, target.isoformat()) - 1
        return dates[idx] if idx >= 0 else None

    candidates: list[tuple[str, str]] = []  # (event_type, resolved_or_raw_date)
    for y, m in _month_range(first_d, horizon_end):
        friday = _first_friday(y, m)
        snapped = _snap(friday)
        candidates.append((US_JOBS_REPORT, snapped or friday.isoformat()))

        first_of_month = date(y, m, 1)
        if first_of_month >= gst_start:
            snapped = _snap(first_of_month)
            candidates.append((INDIA_GST_COLLECTION, snapped or first_of_month.isoformat()))

        # MCX gold/silver expiry — 5th calendar day, snapped back to the
        # nearest earlier trading day when that's a weekend/holiday
        fifth = date(y, m, 5)
        snapped_back = _snap_back(fifth)
        resolved_fifth = snapped_back or fifth.isoformat()
        candidates.append((MCX_GOLD_EXPIRY, resolved_fifth))
        candidates.append((MCX_SILVER_EXPIRY, resolved_fifth))

        # COMEX gold/silver expiry — a rougher approximation: the 27th
        # calendar day (a rule-of-thumb stand-in for "a few business days
        # before month end"), snapped back the same way, against NSE's
        # calendar since that's the only one this system has (COMEX and NSE
        # don't share holidays, so this can be off by a day or more)
        twenty_seventh = date(y, m, 27)
        snapped_back_comex = _snap_back(twenty_seventh)
        resolved_27th = snapped_back_comex or twenty_seventh.isoformat()
        candidates.append((COMEX_GOLD_EXPIRY, resolved_27th))
        candidates.append((COMEX_SILVER_EXPIRY, resolved_27th))

    for thursday in _thursdays(first_d, horizon_end_day):
        snapped = _snap(thursday)
        candidates.append((US_JOBLESS_CLAIMS, snapped or thursday.isoformat()))

    for d in fno_expiry_dates:
        candidates.append((FNO_EXPIRY, d))
    for d in fomc_dates:
        candidates.append((FED_RATE_DECISION, d))
    for d in ecb_dates:
        candidates.append((ECB_RATE_DECISION, d))
    for d in rbi_dates:
        candidates.append((RBI_RATE_DECISION, d))

    def _bar(idx: int) -> float | None:
        return closes[idx] if 0 <= idx < n else None

    occurrences: list[EventOccurrence] = []
    for event_type, ev_date in candidates:
        idx = bisect.bisect_left(dates, ev_date)
        if idx >= n or dates[idx] != ev_date:
            # not an exact trading date in our series (future, or a date
            # outside the loaded range) -> list it with no price data
            occurrences.append(EventOccurrence(event_type=event_type, event_date=ev_date))
            continue
        prior_close = _bar(idx - 1) if idx > 0 else None
        close = closes[idx]
        next_close = _bar(idx + 1)
        change_pct = round((close - prior_close) / prior_close * 100.0, 3) if prior_close else None
        next_change_pct = (
            round((next_close - close) / close * 100.0, 3) if next_close and close else None
        )
        occurrences.append(
            EventOccurrence(
                event_type=event_type,
                event_date=ev_date,
                prior_close=round(prior_close, 4) if prior_close is not None else None,
                close=round(close, 4),
                change_pct=change_pct,
                next_close=round(next_close, 4) if next_close is not None else None,
                next_change_pct=next_change_pct,
            )
        )

    occurrences.sort(key=lambda o: (o.event_date, o.event_type))

    summaries: list[EventTypeSummary] = []
    for event_type in _ALL_EVENT_TYPES:
        group = [o for o in occurrences if o.event_type == event_type]
        resolved = [o for o in group if o.change_pct is not None]
        abs_changes = [abs(o.change_pct) for o in resolved if o.change_pct is not None]
        up = sum(1 for o in resolved if o.change_pct is not None and o.change_pct > 0)
        down = sum(1 for o in resolved if o.change_pct is not None and o.change_pct < 0)
        summaries.append(
            EventTypeSummary(
                event_type=event_type,
                n_occurrences=len(group),
                n_resolved=len(resolved),
                mean_abs_change_pct=round(mean(abs_changes), 3) if abs_changes else None,
                median_abs_change_pct=(
                    round(float(median(abs_changes)), 3) if abs_changes else None
                ),
                pct_notable_move=(
                    round(sum(1 for a in abs_changes if a >= notable) / len(abs_changes) * 100.0, 1)
                    if abs_changes
                    else None
                ),
                up_count=up,
                down_count=down,
            )
        )

    return EventCalendarResult(
        status="OK",
        reason=None,
        notable_move_pct=notable,
        summaries=summaries,
        occurrences=occurrences,
    )
