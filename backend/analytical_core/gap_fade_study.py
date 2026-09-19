"""Gap-fade streak study — what tends to happen after a day that gaps one
way but closes the other: how long the reversal-direction streak runs, where
it consolidates, and which way it eventually breaks.

Pure and deterministic. Not a backtest (no entry/exit/target/stop, no
hit-rate against a trade) — a descriptive historical study, covering **both**
reversal directions (owner: "open low close/open high close actually it
represent the reversal" — the gap-down-then-close-up case is just as much a
reversal as the gap-up-then-close-down one, and was missing from the first
version of this study):

- **UP** — gapped up (open vs prior close) and still closed down, by at
  least the configured thresholds. A bearish reversal candidate; the
  following streak is counted in lower-closing days.
- **DOWN** — gapped down and still closed up. A bullish reversal candidate;
  the following streak is counted in higher-closing days.

For every qualifying day, walk forward through the actual daily bars that
followed and record three things:

1. **Streak** — the run of consecutive closes continuing in the reversal's
   own direction, starting on the event day itself (which is already such a
   day by definition) — lower closes after a UP event, higher closes after
   a DOWN event.
2. **Consolidation box** — the high/low of the first ``box_days`` days right
   after the streak ends, and how many days price then stayed inside it.
3. **Breakout** — the first day price closes beyond that box by
   ``breakout_buffer_pct``, and which direction (independent of the
   triggering event's own direction — a UP event's streak can break out
   either way once it reaches consolidation, same for DOWN).

Aggregated per direction into a distribution (streak lengths, consolidation
lengths, breakout-direction split) — descriptive only, no BUY/SELL, no
signal.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from statistics import mean, median
from typing import Any

GAP_FADE_STUDY_VERSION = "0.2.0"

DEFAULTS: dict[str, Any] = {
    "gap_up_min_pct": 0.5,  # gap_pct >= this counts as "gapped up" (percent, e.g. 0.5 = 0.5%)
    "chg_down_max_pct": -0.5,  # change_pct <= this counts as "closed down" (percent)
    "gap_down_max_pct": -0.5,  # gap_pct <= this counts as "gapped down" (percent)
    "chg_up_min_pct": 0.5,  # change_pct >= this counts as "closed up" (percent)
    "box_days": 3,  # days right after the streak ends that define the consolidation box
    "breakout_buffer_pct": 0.3,  # close must clear the box by this % to count as a breakout
    "max_breakout_search_days": 90,  # give up looking for a breakout after this many days
    "max_occurrences": 200,  # safety cap on how many historical events to detail, per direction
}

_UP = "UP"  # gapped up, closed down -> bearish reversal candidate, tracks a down-streak
_DOWN = "DOWN"  # gapped down, closed up -> bullish reversal candidate, tracks an up-streak
_DIRECTIONS = (_UP, _DOWN)

_STREAK_ONGOING = "STREAK_ONGOING"
_INSUFFICIENT_BOX_DATA = "INSUFFICIENT_BOX_DATA"
_CONSOLIDATING = "CONSOLIDATING"
_BREAKOUT_UP = "BREAKOUT_UP"
_BREAKOUT_DOWN = "BREAKOUT_DOWN"


@dataclass(frozen=True, slots=True)
class GapFadeOccurrence:
    event_date: str
    direction: str  # UP (gap up, closed down) | DOWN (gap down, closed up)
    gap_pct: float
    change_pct: float
    streak_days: int
    streak_end_date: str
    status: str  # STREAK_ONGOING | INSUFFICIENT_BOX_DATA | CONSOLIDATING | BREAKOUT_UP/DOWN
    box_start_date: str | None = None
    box_high: float | None = None
    box_low: float | None = None
    consolidation_days: int | None = None  # days spent inside the box so far (or until breakout)
    breakout_date: str | None = None
    breakout_direction: str | None = None  # UP | DOWN | None


@dataclass(frozen=True, slots=True)
class GapFadeSummary:
    direction: str  # UP | DOWN
    n_occurrences: int
    n_streak_resolved: int  # streak fully played out within the loaded data
    mean_streak_days: float | None = None
    median_streak_days: float | None = None
    streak_day_histogram: dict[int, int] = field(default_factory=dict)
    n_breakout_resolved: int = 0  # box formed AND a breakout direction found
    mean_consolidation_days: float | None = None
    median_consolidation_days: float | None = None
    breakout_up_count: int = 0
    breakout_down_count: int = 0
    breakout_up_pct: float | None = None  # of resolved breakouts, % that went up


@dataclass(frozen=True, slots=True)
class GapFadeStudyResult:
    status: str  # OK | INSUFFICIENT_DATA
    reason: str | None
    summaries: list[GapFadeSummary] = field(default_factory=list)  # one per direction, UP then DOWN
    occurrences: list[GapFadeOccurrence] = field(default_factory=list)
    gap_fade_study_version: str = GAP_FADE_STUDY_VERSION


def scan_gap_fade_study(
    dates: Sequence[str],
    opens: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    *,
    params: Mapping[str, Any] | None = None,
) -> GapFadeStudyResult:
    """``dates``/``opens``/``highs``/``lows``/``closes`` chronological daily
    bars, same length, ``dates`` as ISO ``YYYY-MM-DD`` strings."""
    p = {**DEFAULTS, **(params or {})}
    gap_up_min = float(p["gap_up_min_pct"])
    chg_down_max = float(p["chg_down_max_pct"])
    gap_down_max = float(p["gap_down_max_pct"])
    chg_up_min = float(p["chg_up_min_pct"])
    box_days_n = int(p["box_days"])
    buf = float(p["breakout_buffer_pct"]) / 100.0
    max_search = int(p["max_breakout_search_days"])
    max_occ = int(p["max_occurrences"])

    n = len(dates)
    if n < box_days_n + 2:
        return GapFadeStudyResult(
            status="INSUFFICIENT_DATA",
            reason=f"need >= {box_days_n + 2} daily bars, have {n}",
        )

    occurrences: list[GapFadeOccurrence] = []
    for i in range(1, n):
        prior_close = closes[i - 1]
        if not prior_close:
            continue
        gap_pct = (opens[i] - prior_close) / prior_close * 100.0
        change_pct = (closes[i] - prior_close) / prior_close * 100.0
        if gap_pct >= gap_up_min and change_pct <= chg_down_max:
            direction = _UP
        elif gap_pct <= gap_down_max and change_pct >= chg_up_min:
            direction = _DOWN
        else:
            continue

        # 1. streak, continuing in the reversal's own direction, starting on
        # the event day itself
        j = i + 1
        if direction == _UP:
            while j < n and closes[j] < closes[j - 1]:
                j += 1
        else:
            while j < n and closes[j] > closes[j - 1]:
                j += 1
        streak_days = j - i  # event day counts as day 1
        streak_end_idx = j - 1

        if j >= n:
            occurrences.append(
                GapFadeOccurrence(
                    event_date=dates[i],
                    direction=direction,
                    gap_pct=round(gap_pct, 3),
                    change_pct=round(change_pct, 3),
                    streak_days=streak_days,
                    streak_end_date=dates[streak_end_idx],
                    status=_STREAK_ONGOING,
                )
            )
            continue

        # 2. consolidation box from the first box_days_n bars after the streak
        box_start = j
        box_end = min(box_start + box_days_n, n)
        if box_end - box_start < box_days_n:
            occurrences.append(
                GapFadeOccurrence(
                    event_date=dates[i],
                    direction=direction,
                    gap_pct=round(gap_pct, 3),
                    change_pct=round(change_pct, 3),
                    streak_days=streak_days,
                    streak_end_date=dates[streak_end_idx],
                    status=_INSUFFICIENT_BOX_DATA,
                )
            )
            continue
        box_high = max(highs[box_start:box_end])
        box_low = min(lows[box_start:box_end])

        # 3. scan forward for the first close that clears the box by the buffer
        breakout_idx: int | None = None
        breakout_dir: str | None = None
        search_end = min(box_end + max_search, n)
        k = box_end
        while k < search_end:
            if closes[k] > box_high * (1 + buf):
                breakout_idx, breakout_dir = k, "UP"
                break
            if closes[k] < box_low * (1 - buf):
                breakout_idx, breakout_dir = k, "DOWN"
                break
            k += 1

        if breakout_idx is not None:
            occurrences.append(
                GapFadeOccurrence(
                    event_date=dates[i],
                    direction=direction,
                    gap_pct=round(gap_pct, 3),
                    change_pct=round(change_pct, 3),
                    streak_days=streak_days,
                    streak_end_date=dates[streak_end_idx],
                    status=_BREAKOUT_UP if breakout_dir == "UP" else _BREAKOUT_DOWN,
                    box_start_date=dates[box_start],
                    box_high=round(box_high, 4),
                    box_low=round(box_low, 4),
                    consolidation_days=breakout_idx - box_start,
                    breakout_date=dates[breakout_idx],
                    breakout_direction=breakout_dir,
                )
            )
        else:
            occurrences.append(
                GapFadeOccurrence(
                    event_date=dates[i],
                    direction=direction,
                    gap_pct=round(gap_pct, 3),
                    change_pct=round(change_pct, 3),
                    streak_days=streak_days,
                    streak_end_date=dates[streak_end_idx],
                    status=_CONSOLIDATING,
                    box_start_date=dates[box_start],
                    box_high=round(box_high, 4),
                    box_low=round(box_low, 4),
                    consolidation_days=search_end - box_start,
                )
            )

    summaries: list[GapFadeSummary] = []
    for direction in _DIRECTIONS:
        group = [o for o in occurrences if o.direction == direction]
        resolved_streaks = [o for o in group if o.status != _STREAK_ONGOING]
        streak_lengths = [o.streak_days for o in resolved_streaks]
        histogram: dict[int, int] = {}
        for sl in streak_lengths:
            histogram[sl] = histogram.get(sl, 0) + 1

        breakouts = [o for o in group if o.status in (_BREAKOUT_UP, _BREAKOUT_DOWN)]
        consolidation_lengths = [
            o.consolidation_days for o in breakouts if o.consolidation_days is not None
        ]
        up_count = sum(1 for o in breakouts if o.status == _BREAKOUT_UP)
        down_count = sum(1 for o in breakouts if o.status == _BREAKOUT_DOWN)

        summaries.append(
            GapFadeSummary(
                direction=direction,
                n_occurrences=len(group),
                n_streak_resolved=len(resolved_streaks),
                mean_streak_days=round(mean(streak_lengths), 2) if streak_lengths else None,
                median_streak_days=(
                    round(float(median(streak_lengths)), 2) if streak_lengths else None
                ),
                streak_day_histogram=dict(sorted(histogram.items())),
                n_breakout_resolved=len(breakouts),
                mean_consolidation_days=(
                    round(mean(consolidation_lengths), 2) if consolidation_lengths else None
                ),
                median_consolidation_days=(
                    round(float(median(consolidation_lengths)), 2)
                    if consolidation_lengths
                    else None
                ),
                breakout_up_count=up_count,
                breakout_down_count=down_count,
                breakout_up_pct=(
                    round(up_count / (up_count + down_count) * 100.0, 1)
                    if (up_count + down_count)
                    else None
                ),
            )
        )

    # newest first for the detail list; cap it per direction, the summary
    # already covers everything
    up_occ = sorted(
        (o for o in occurrences if o.direction == _UP), key=lambda o: o.event_date, reverse=True
    )[:max_occ]
    down_occ = sorted(
        (o for o in occurrences if o.direction == _DOWN), key=lambda o: o.event_date, reverse=True
    )[:max_occ]
    all_occ = sorted(up_occ + down_occ, key=lambda o: o.event_date, reverse=True)

    return GapFadeStudyResult(
        status="OK",
        reason=None,
        summaries=summaries,
        occurrences=all_occ,
    )
