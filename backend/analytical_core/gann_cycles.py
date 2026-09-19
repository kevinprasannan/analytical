"""Gann time cycles — classic W.D. Gann day-count projections from the most
recent significant swing low and swing high.

Pure and deterministic. Finds the lowest low and the highest high over a
lookback window of daily bars — the "previous low" / "previous high" anchors
— then projects each of Gann's classic day-count cycles (45 / 90 / 120 / 144
/ 180 / 270 / 360 calendar days by default) forward from each anchor. A date
where several projections from different anchors/cycles land within
``cluster_tolerance_days`` of each other is flagged as a confluence cluster —
a stronger "time turn" candidate by Gann's method.

Descriptive: these are calendar dates a turn is more likely by this method,
not a trade signal. No BUY/SELL, no entry/target/stop.
"""

from __future__ import annotations

import bisect
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

GANN_CYCLES_VERSION = "0.1.0"

DEFAULTS: dict[str, Any] = {
    "lookback_bars": 260,  # daily bars (~1y) searched for the anchor swing low/high
    "cycle_days": (45, 90, 120, 144, 180, 270, 360),  # classic Gann day-counts (calendar days)
    "cluster_tolerance_days": 2,  # projections within this many days of each other cluster
    "horizon_days": 60,  # keep only projected dates within +/- this many days of "today"
}


@dataclass(frozen=True, slots=True)
class GannAnchor:
    kind: str  # LOW | HIGH
    anchor_date: str  # ISO date
    price: float


@dataclass(frozen=True, slots=True)
class GannProjection:
    anchor_kind: str  # LOW | HIGH
    anchor_date: str
    anchor_price: float
    cycle_days: int
    target_date: str
    days_from_today: int  # signed; negative = past, positive = upcoming, 0 = today
    # what actually happened, filled in only when target_date already has a bar
    # (the nearest trading date on/after it, within the loaded series) — None
    # for a projection that's still in the future
    resolved_date: str | None = None
    actual_close: float | None = None
    actual_high: float | None = None
    actual_low: float | None = None


@dataclass(frozen=True, slots=True)
class GannCluster:
    cluster_date: str  # earliest target date in the group
    days_from_today: int
    strength: int  # number of contributing projections
    projections: list[GannProjection] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class GannCyclesResult:
    status: str  # OK | INSUFFICIENT_DATA
    reason: str | None
    swing_low: GannAnchor | None
    swing_high: GannAnchor | None
    projections: list[GannProjection] = field(default_factory=list)
    clusters: list[GannCluster] = field(default_factory=list)
    gann_cycles_version: str = GANN_CYCLES_VERSION


def scan_gann_cycles(
    dates: Sequence[str],
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    *,
    today: str,
    params: Mapping[str, Any] | None = None,
) -> GannCyclesResult:
    """``dates``/``highs``/``lows``/``closes`` chronological daily bars, same
    length — ``dates`` as ISO ``YYYY-MM-DD`` strings (trading date, not a
    timestamp). ``today`` is an ISO date to measure projections against.
    A projection whose ``target_date`` already has a bar on or shortly after
    it (within the loaded ``dates``) is filled with what actually happened
    there — the nearest trading date on/after ``target_date`` (weekends and
    holidays land on the next session), and that bar's close/high/low. A
    projection past the end of the loaded series (still in the future) is
    left unfilled."""
    p = {**DEFAULTS, **(params or {})}
    lookback = int(p["lookback_bars"])
    cycle_days = tuple(int(x) for x in p["cycle_days"])
    tol = int(p["cluster_tolerance_days"])
    horizon = int(p["horizon_days"])

    n = len(dates)
    if n < 5:
        return GannCyclesResult(
            status="INSUFFICIENT_DATA",
            reason=f"need >= 5 daily bars, have {n}",
            swing_low=None,
            swing_high=None,
        )

    start = max(0, n - lookback)
    window = range(start, n)
    lo_i = min(window, key=lambda i: lows[i])
    hi_i = max(window, key=lambda i: highs[i])

    swing_low = GannAnchor(kind="LOW", anchor_date=dates[lo_i], price=round(lows[lo_i], 4))
    swing_high = GannAnchor(kind="HIGH", anchor_date=dates[hi_i], price=round(highs[hi_i], 4))

    def _resolve(target_iso: str) -> tuple[str | None, float | None, float | None, float | None]:
        """Nearest trading date on/after ``target_iso`` within ``dates``, and
        that bar's close/high/low — or all-``None`` if it's beyond the data
        we have (still in the future)."""
        idx = bisect.bisect_left(dates, target_iso)
        if idx >= len(dates):
            return None, None, None, None
        return dates[idx], closes[idx], highs[idx], lows[idx]

    today_d = date.fromisoformat(today)
    projections: list[GannProjection] = []
    for anchor in (swing_low, swing_high):
        adate = date.fromisoformat(anchor.anchor_date)
        for cd in cycle_days:
            tdate = adate + timedelta(days=cd)
            days_from_today = (tdate - today_d).days
            if abs(days_from_today) > horizon:
                continue
            resolved_date, actual_close, actual_high, actual_low = _resolve(tdate.isoformat())
            projections.append(
                GannProjection(
                    anchor_kind=anchor.kind,
                    anchor_date=anchor.anchor_date,
                    anchor_price=anchor.price,
                    cycle_days=cd,
                    target_date=tdate.isoformat(),
                    days_from_today=days_from_today,
                    resolved_date=resolved_date,
                    actual_close=round(actual_close, 4) if actual_close is not None else None,
                    actual_high=round(actual_high, 4) if actual_high is not None else None,
                    actual_low=round(actual_low, 4) if actual_low is not None else None,
                )
            )
    projections.sort(key=lambda x: x.target_date)

    # single-linkage clustering: walk chronologically, absorb any later
    # projection within `tol` days of the item that opened the current group
    clusters: list[GannCluster] = []
    used = [False] * len(projections)
    for i, p_i in enumerate(projections):
        if used[i]:
            continue
        group = [p_i]
        used[i] = True
        d_i = date.fromisoformat(p_i.target_date)
        for j in range(i + 1, len(projections)):
            if used[j]:
                continue
            d_j = date.fromisoformat(projections[j].target_date)
            if abs((d_j - d_i).days) <= tol:
                group.append(projections[j])
                used[j] = True
        if len(group) >= 2:
            clusters.append(
                GannCluster(
                    cluster_date=group[0].target_date,
                    days_from_today=group[0].days_from_today,
                    strength=len(group),
                    projections=group,
                )
            )
    clusters.sort(key=lambda c: c.cluster_date)

    return GannCyclesResult(
        status="OK",
        reason=None,
        swing_low=swing_low,
        swing_high=swing_high,
        projections=projections,
        clusters=clusters,
    )
