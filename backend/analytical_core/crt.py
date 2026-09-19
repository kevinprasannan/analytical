"""Candle Range Theory (CRT) — a reference candle's High-Low range, and how
later candles behave around it.

Pure and deterministic. A candle's high/low sets a **reference range**; the
candles that follow it are read against four boundaries — the high, the low,
the midpoint, and "inside" — to say whether the range is being **accepted**
(holds beyond a break), **rejected** (breaks then closes back inside), or
**expanded** (price keeps travelling beyond the broken level). Separately, a
reference candle that sits entirely inside its own prior bar is flagged as a
**compression** ("inside"/"mother") candle, since the eventual break of that
prior bar's own high/low then matters more.

Not "green candle = bullish" — the range boundaries and what happens *after*
a break are the whole point. Descriptive: no BUY/SELL, no entry/target/stop.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

CRT_VERSION = "0.1.0"

DEFAULTS: dict[str, float] = {
    "scan_bars": 5,  # how many bars after the reference candle to read as reaction
    "at_midpoint_pct": 0.1,  # band around the midpoint (fraction of range) counted as "at midpoint"
    "retest_tol_pct": 0.05,  # how close a pullback must come to the level to count as a retest
    "expansion_multiple_strong": 0.5,  # extension beyond the break, as a multiple of ref_range
    "volume_confirm_multiple": 1.2,  # breakout-bar volume vs. window average, to call it confirmed
}


class CrtPosition(StrEnum):
    ABOVE_HIGH = "ABOVE_HIGH"
    BELOW_LOW = "BELOW_LOW"
    INSIDE = "INSIDE"
    AT_MIDPOINT = "AT_MIDPOINT"


class CrtBreakout(StrEnum):
    NONE = "NONE"
    HIGH = "HIGH"
    LOW = "LOW"


class CrtSignal(StrEnum):
    BULLISH_CONTINUATION = "BULLISH_CONTINUATION"
    BEARISH_CONTINUATION = "BEARISH_CONTINUATION"
    HIGH_REJECTION = "HIGH_REJECTION"
    LOW_REJECTION = "LOW_REJECTION"
    RANGE_EXPANSION_UP = "RANGE_EXPANSION_UP"
    RANGE_EXPANSION_DOWN = "RANGE_EXPANSION_DOWN"
    COMPRESSION = "COMPRESSION"
    NEUTRAL = "NEUTRAL"


@dataclass(frozen=True, slots=True)
class CrtRead:
    reference_index: int
    reference_ts: str | None
    ref_high: float
    ref_low: float
    ref_range: float
    ref_midpoint: float
    is_inside_candle: bool  # the reference candle sat fully inside its own prior ("mother") bar
    mother_high: float | None
    mother_low: float | None
    last_ts: str | None
    last_close: float
    current_position: str  # CrtPosition
    breakout_direction: str  # CrtBreakout
    breakout_ts: str | None
    close_outside: bool  # latest close is still beyond the broken level
    returned_inside: bool  # broke, then the latest close came back inside — rejection
    retested: bool  # pulled back to the broken level, then continued past it
    holds_beyond: bool  # latest bar's own wick, not just its close, stayed clear of the level
    expansion_points: float | None  # furthest travel beyond the broken level since the break
    expansion_multiple: float | None  # expansion_points / ref_range
    volume_confirms: bool | None  # breakout-bar volume vs. the window average (None = no data)
    signal: str  # CrtSignal
    bars_scanned: int
    crt_version: str = CRT_VERSION


def scan_crt(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    *,
    volumes: Sequence[float] | None = None,
    ts: Sequence[str] | None = None,
    params: Mapping[str, float] | None = None,
) -> CrtRead | None:
    """``highs``/``lows``/``closes`` chronological, same length. The reference
    candle is the bar ``scan_bars`` back from the end; every bar after it is
    the "reaction" window read against its high/low/midpoint. ``None`` when
    there aren't enough bars."""
    p = {**DEFAULTS, **(params or {})}
    scan = int(p["scan_bars"])
    n = len(closes)
    if n < scan + 1 or scan < 1:
        return None

    ref_i = n - scan - 1
    reacting_start = ref_i + 1
    mother_i = ref_i - 1 if ref_i >= 1 else None

    def _tsat(i: int) -> str | None:
        return ts[i] if ts is not None and 0 <= i < len(ts) else None

    ref_high, ref_low = float(highs[ref_i]), float(lows[ref_i])
    ref_range = ref_high - ref_low
    ref_mid = (ref_high + ref_low) / 2.0

    mother_high = mother_low = None
    is_inside = False
    if mother_i is not None:
        mother_high, mother_low = float(highs[mother_i]), float(lows[mother_i])
        is_inside = ref_high <= mother_high and ref_low >= mother_low

    # first breakout in the reacting window, chronologically
    breakout_dir = CrtBreakout.NONE.value
    breakout_i: int | None = None
    for i in range(reacting_start, n):
        hi, lo, cl = float(highs[i]), float(lows[i]), float(closes[i])
        broke_high, broke_low = hi > ref_high, lo < ref_low
        if broke_high and broke_low:
            # a single bar spanning both edges — resolve by where it closed
            if cl > ref_high:
                breakout_dir, breakout_i = CrtBreakout.HIGH.value, i
            elif cl < ref_low:
                breakout_dir, breakout_i = CrtBreakout.LOW.value, i
            break
        if broke_high:
            breakout_dir, breakout_i = CrtBreakout.HIGH.value, i
            break
        if broke_low:
            breakout_dir, breakout_i = CrtBreakout.LOW.value, i
            break

    last_i = n - 1
    last_close = float(closes[last_i])

    mid_band = ref_range * float(p["at_midpoint_pct"])
    if last_close > ref_high:
        position = CrtPosition.ABOVE_HIGH.value
    elif last_close < ref_low:
        position = CrtPosition.BELOW_LOW.value
    elif abs(last_close - ref_mid) <= mid_band:
        position = CrtPosition.AT_MIDPOINT.value
    else:
        position = CrtPosition.INSIDE.value

    close_outside = False
    returned_inside = False
    retested = False
    holds_beyond = False
    expansion_points: float | None = None
    expansion_multiple: float | None = None
    volume_confirms: bool | None = None

    if breakout_dir != CrtBreakout.NONE.value and breakout_i is not None:
        up = breakout_dir == CrtBreakout.HIGH.value
        level = ref_high if up else ref_low
        close_outside = (last_close > level) if up else (last_close < level)
        returned_inside = not close_outside
        holds_beyond = close_outside and (
            (float(lows[last_i]) >= level) if up else (float(highs[last_i]) <= level)
        )
        tol = ref_range * float(p["retest_tol_pct"])
        for i in range(breakout_i + 1, n):
            touched = (float(lows[i]) <= level + tol) if up else (float(highs[i]) >= level - tol)
            if touched:
                retested = close_outside  # only "a retest" if price ultimately continued past it
                break
        extremes = [float(highs[i]) if up else float(lows[i]) for i in range(breakout_i, n)]
        if extremes:
            far = max(extremes) if up else min(extremes)
            expansion_points = round((far - level) if up else (level - far), 4)
            expansion_multiple = round(expansion_points / ref_range, 4) if ref_range else None
        if volumes is not None and 0 <= breakout_i < len(volumes):
            window = [float(volumes[i]) for i in range(ref_i, n) if i != breakout_i]
            avg = sum(window) / len(window) if window else 0.0
            volume_confirms = (
                float(volumes[breakout_i]) >= avg * float(p["volume_confirm_multiple"])
                if avg > 0
                else None
            )

    if breakout_dir == CrtBreakout.NONE.value:
        signal = CrtSignal.COMPRESSION.value if is_inside else CrtSignal.NEUTRAL.value
    elif breakout_dir == CrtBreakout.HIGH.value:
        if returned_inside:
            signal = CrtSignal.HIGH_REJECTION.value
        elif expansion_multiple is not None and expansion_multiple >= float(
            p["expansion_multiple_strong"]
        ):
            signal = CrtSignal.RANGE_EXPANSION_UP.value
        elif close_outside:
            signal = CrtSignal.BULLISH_CONTINUATION.value
        else:
            signal = CrtSignal.NEUTRAL.value
    else:
        if returned_inside:
            signal = CrtSignal.LOW_REJECTION.value
        elif expansion_multiple is not None and expansion_multiple >= float(
            p["expansion_multiple_strong"]
        ):
            signal = CrtSignal.RANGE_EXPANSION_DOWN.value
        elif close_outside:
            signal = CrtSignal.BEARISH_CONTINUATION.value
        else:
            signal = CrtSignal.NEUTRAL.value

    return CrtRead(
        reference_index=ref_i,
        reference_ts=_tsat(ref_i),
        ref_high=round(ref_high, 4),
        ref_low=round(ref_low, 4),
        ref_range=round(ref_range, 4),
        ref_midpoint=round(ref_mid, 4),
        is_inside_candle=is_inside,
        mother_high=round(mother_high, 4) if mother_high is not None else None,
        mother_low=round(mother_low, 4) if mother_low is not None else None,
        last_ts=_tsat(last_i),
        last_close=round(last_close, 4),
        current_position=position,
        breakout_direction=breakout_dir,
        breakout_ts=_tsat(breakout_i) if breakout_i is not None else None,
        close_outside=close_outside,
        returned_inside=returned_inside,
        retested=retested,
        holds_beyond=holds_beyond,
        expansion_points=expansion_points,
        expansion_multiple=expansion_multiple,
        volume_confirms=volume_confirms,
        signal=signal,
        bars_scanned=n - ref_i,
    )
