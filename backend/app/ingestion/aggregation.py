"""M1 → session-anchored M5 / M15 / H1 aggregation (Phase 2.4, docs/05 §3.5).

Pure and in-memory. Input is a sequence of **M1** ``OHLCVBar`` DTOs
(provider-neutral, bar-open UTC); output is ``OHLCVBar`` rows on the
session-anchored grid of :mod:`app.ingestion.session`. Nothing here persists,
watermarks, or talks to a provider (2.5 / 2.6 own that).

Per-period rule (docs/05 §3.5)::

    open  = first child open (by ts)
    high  = max child high
    low   = min child low
    close = last child close (by ts)
    volume = Σ child volume
    open_interest = last child open_interest (OI is a level, not a flow)

* a period with **zero** child M1 bars is **not emitted** (docs/05 §3.4 — no
  fabricated / carried bars);
* ``is_final`` = (every covered child is final) **and** (the period ended at
  least ``finalize_grace_seconds`` ago) (docs/05 §3.5 / §3.6);
* the bar ``ts`` is the **grid anchor**, never the first child's ts — a period
  that starts with a gap still anchors to the session grid.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from analytical_core.enums import Timeframe
from app.ingestion.session import (
    AGGREGATED_TIMEFRAMES,
    GridPeriod,
    SessionWindow,
    nse_session_window,
    session_grid,
    trading_date_of,
)
from app.providers.base import OHLCVBar

_INTERVAL_MIN = {Timeframe.M5: 5, Timeframe.M15: 15, Timeframe.H1: 60}

#: provenance marker on an aggregated bar. The child source string(s) are kept
#: inside the parens so a synthetic origin (``STUB_FIXTURE``) stays visible and
#: is never mistaken for real market data (docs/09 §2.5).
AGGREGATE_SOURCE = "aggregate:M1"


@dataclass(frozen=True, slots=True)
class AggregationResult:
    timeframe: Timeframe
    bars: list[OHLCVBar]
    #: grid periods that had no child M1 bar — reported, never emitted as a row.
    empty_periods: list[GridPeriod]


def _agg_source(children: Sequence[OHLCVBar]) -> str:
    seen = sorted({b.source for b in children if b.source})
    return f"{AGGREGATE_SOURCE}({'|'.join(seen)})" if seen else AGGREGATE_SOURCE


def _fold_period(
    period: GridPeriod,
    children: list[OHLCVBar],
    *,
    now: datetime,
    grace: timedelta,
) -> OHLCVBar:
    kids = sorted(children, key=lambda b: b.ts)
    first, last = kids[0], kids[-1]
    period_final = now >= period.end_utc + grace
    return OHLCVBar(
        ts=period.start_utc,
        open=first.open,
        high=max(b.high for b in kids),
        low=min(b.low for b in kids),
        close=last.close,
        volume=sum(b.volume for b in kids),
        is_final=all(b.is_final for b in kids) and period_final,
        source=_agg_source(kids),
        open_interest=last.open_interest,
    )


def aggregate_m1(
    m1_bars: Sequence[OHLCVBar],
    target: Timeframe,
    *,
    session_for: Callable[[date], SessionWindow] = nse_session_window,
    finalize_grace_seconds: int = 90,
    now: datetime | None = None,
) -> AggregationResult:
    """Aggregate M1 ``OHLCVBar`` DTOs to ``target`` ∈ {M5, M15, H1}.

    ``m1_bars`` may span multiple trading dates; they are grouped by IST session
    date. Bars outside a session's ``[open, close)`` (pre-open / post-close,
    docs/05 §3.1) are excluded from analytical input.
    """
    if target not in _INTERVAL_MIN:
        raise ValueError(
            f"aggregate_m1 target must be one of {[t.value for t in AGGREGATED_TIMEFRAMES]}; "
            f"got {target.value}"
        )
    now = now or datetime.now(tz=UTC)
    grace = timedelta(seconds=finalize_grace_seconds)
    interval = timedelta(minutes=_INTERVAL_MIN[target])

    for b in m1_bars:
        if b.ts.tzinfo is None:
            raise ValueError("M1 bar timestamps must be tz-aware UTC")

    by_date: dict[date, list[OHLCVBar]] = {}
    for b in m1_bars:
        by_date.setdefault(trading_date_of(b.ts), []).append(b)

    out_bars: list[OHLCVBar] = []
    empty: list[GridPeriod] = []
    for tdate in sorted(by_date):
        window = session_for(tdate)
        grid = session_grid(window, target)
        buckets: list[list[OHLCVBar]] = [[] for _ in grid]
        for b in by_date[tdate]:
            if not window.contains(b.ts):
                continue  # pre-open / post-close — excluded (docs/05 §3.1)
            idx = (b.ts - window.open_utc) // interval
            if idx >= len(grid):  # defensive: covered by window.contains
                continue
            buckets[idx].append(b)
        for period, children in zip(grid, buckets, strict=True):
            if not children:
                empty.append(period)
                continue
            out_bars.append(_fold_period(period, children, now=now, grace=grace))

    return AggregationResult(timeframe=target, bars=out_bars, empty_periods=empty)


def aggregate_all(
    m1_bars: Sequence[OHLCVBar],
    *,
    targets: Sequence[Timeframe] = AGGREGATED_TIMEFRAMES,
    session_for: Callable[[date], SessionWindow] = nse_session_window,
    finalize_grace_seconds: int = 90,
    now: datetime | None = None,
) -> dict[Timeframe, AggregationResult]:
    now = now or datetime.now(tz=UTC)
    return {
        tf: aggregate_m1(
            m1_bars,
            tf,
            session_for=session_for,
            finalize_grace_seconds=finalize_grace_seconds,
            now=now,
        )
        for tf in targets
    }
