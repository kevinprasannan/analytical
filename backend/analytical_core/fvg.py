"""ICT Fair Value Gaps around swing highs / lows — 'left-side' precision arrays.

Pure and deterministic. Finds the Fair Value Gaps that form in the final
expansion leg **into** a confirmed swing high or low (ICT: institutional
distribution, not continuation). Once price rotates off the swing the gap is an
**inversion** FVG — it flips polarity and tends to act as the opposite of a
normal FVG. Each gap carries its CE (consequent encroachment, the 50 % level),
a fill / test / inversion state, and whether wicks pierced it while candle
bodies respected it.

Descriptive: it maps where the imbalances are and how price has treated them.
No BUY/SELL, no entry / target / stop.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

FVG_VERSION = "0.1.0"

DEFAULTS: dict[str, float] = {
    "swing_lookback": 3,  # fractal strictness each side of a swing
    "pre_swing_window": 6,  # the FVG's 3rd candle must be this many bars before the swing
    "scan_bars": 90,  # how far back to look for swings
    "max_fvgs": 8,  # cap on returned gaps
    "min_gap_pct": 0.03,  # drop gaps thinner than this % of price (noise)
}


class FvgKind(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"


class FvgSwing(StrEnum):
    HIGH = "HIGH"
    LOW = "LOW"


class FvgState(StrEnum):
    PRIMED = "PRIMED"  # swing confirmed, price rotated away, gap not yet retested
    TESTED = "TESTED"  # price has traded back into the gap since the swing
    RESPECTED = "RESPECTED"  # tested, a wick pierced the far edge but the body held
    BREACHED = "BREACHED"  # a candle body closed through the far edge — clean setup gone


@dataclass(frozen=True, slots=True)
class SwingFvg:
    kind: str  # original polarity of the gap
    inversion_kind: str  # what it acts as after the swing (the opposite)
    swing: str  # HIGH | LOW — the swing it formed into
    top: float
    bottom: float
    ce: float
    formed_index: int
    formed_ts: str | None
    swing_index: int
    swing_ts: str | None
    bars_since_swing: int
    state: str
    reached_ce: bool
    wick_violated: bool
    body_respected: bool
    distance_pct: float  # signed % from last price to the near edge (0 when price is inside)


@dataclass(frozen=True, slots=True)
class FvgScan:
    fvgs: list[SwingFvg] = field(default_factory=list)  # most recent swing first
    last_price: float = 0.0
    nearest_above: SwingFvg | None = None
    nearest_below: SwingFvg | None = None
    bias: str = "NEUTRAL"  # soft lean = inversion_kind of the nearest active gap
    bars_scanned: int = 0
    fvg_version: str = FVG_VERSION


def _swings(vals: Sequence[float], k: int, *, high: bool) -> list[int]:
    out: list[int] = []
    n = len(vals)
    for i in range(k, n - k):
        v = vals[i]
        left = vals[i - k : i]
        right = vals[i + 1 : i + 1 + k]
        if high:
            if all(v > x for x in left) and all(v > x for x in right):
                out.append(i)
        elif all(v < x for x in left) and all(v < x for x in right):
            out.append(i)
    return out


def _bull_gap(highs: Sequence[float], lows: Sequence[float], i: int) -> tuple[float, float] | None:
    """(top, bottom) of a bullish FVG at candle ``i`` — gap between candle i-2's
    high and candle i's low."""
    if i >= 2 and lows[i] > highs[i - 2]:
        return lows[i], highs[i - 2]
    return None


def _bear_gap(highs: Sequence[float], lows: Sequence[float], i: int) -> tuple[float, float] | None:
    if i >= 2 and highs[i] < lows[i - 2]:
        return lows[i - 2], highs[i]
    return None


def _state(
    *,
    resistance: bool,
    top: float,
    bottom: float,
    ce: float,
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    after: int,
    n: int,
) -> tuple[str, bool, bool, bool]:
    """(state, reached_ce, wick_violated, body_respected) from the bars after a swing."""
    far = top if resistance else bottom
    tested = reached_ce = wick_violated = breached = left = False
    for b in range(after, n):
        hi, lo, cl = highs[b], lows[b], closes[b]
        # "left" = price first rotated clear of the gap on the away side …
        if (hi < bottom) if resistance else (lo > top):
            left = True
        # … then a later bar traded back into the zone
        if left and lo <= top and hi >= bottom:
            tested = True
            if (hi >= ce) if resistance else (lo <= ce):
                reached_ce = True
            if (hi > far) if resistance else (lo < far):
                wick_violated = True
            if (cl > far) if resistance else (cl < far):
                breached = True
    body_respected = not breached
    if breached:
        st = FvgState.BREACHED
    elif not tested:
        st = FvgState.PRIMED
    elif wick_violated and body_respected:
        st = FvgState.RESPECTED
    else:
        st = FvgState.TESTED
    return st.value, reached_ce, wick_violated, body_respected


def scan_swing_fvgs(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    *,
    ts: Sequence[str] | None = None,
    params: Mapping[str, int] | None = None,
) -> FvgScan:
    p = {**DEFAULTS, **(params or {})}
    k = int(p["swing_lookback"])
    win = int(p["pre_swing_window"])
    scan = int(p["scan_bars"])
    n = len(closes)
    if n < 2 * k + 5:
        return FvgScan(last_price=float(closes[-1]) if n else 0.0, bars_scanned=n)

    last = float(closes[-1])
    start = max(0, n - scan)

    def _tsat(i: int) -> str | None:
        return ts[i] if ts is not None and 0 <= i < len(ts) else None

    found: list[SwingFvg] = []

    def _collect(swing_idxs: list[int], *, swing_kind: str, gap_fn, kind: str, inv: str) -> None:
        resistance = swing_kind == FvgSwing.HIGH.value
        for s in swing_idxs:
            if s < start or s >= n:
                continue
            for j in range(max(2, s - win), s):  # strictly before the swing
                g = gap_fn(highs, lows, j)
                if g is None:
                    continue
                top, bottom = g
                # the swing extreme must have expanded *past* the gap — i.e. the
                # gap is genuinely left behind on the leg into the swing
                if (highs[s] <= top) if resistance else (lows[s] >= bottom):
                    continue
                if last and (top - bottom) / last * 100.0 < float(p["min_gap_pct"]):
                    continue  # too thin to matter
                ce = (top + bottom) / 2.0
                st, at_ce, wv, br = _state(
                    resistance=resistance,
                    top=top,
                    bottom=bottom,
                    ce=ce,
                    highs=highs,
                    lows=lows,
                    closes=closes,
                    after=s + 1,
                    n=n,
                )
                if last > top:
                    dist = (bottom - last) / last * 100.0 if last else 0.0  # gap above
                elif last < bottom:
                    dist = (top - last) / last * 100.0 if last else 0.0  # gap below
                else:
                    dist = 0.0  # price inside
                found.append(
                    SwingFvg(
                        kind=kind,
                        inversion_kind=inv,
                        swing=swing_kind,
                        top=round(top, 2),
                        bottom=round(bottom, 2),
                        ce=round(ce, 2),
                        formed_index=j,
                        formed_ts=_tsat(j),
                        swing_index=s,
                        swing_ts=_tsat(s),
                        bars_since_swing=n - 1 - s,
                        state=st,
                        reached_ce=at_ce,
                        wick_violated=wv,
                        body_respected=br,
                        distance_pct=round(dist, 3),
                    )
                )

    _collect(
        _swings(highs, k, high=True),
        swing_kind=FvgSwing.HIGH.value,
        gap_fn=_bull_gap,
        kind=FvgKind.BULLISH.value,
        inv=FvgKind.BEARISH.value,
    )
    _collect(
        _swings(lows, k, high=False),
        swing_kind=FvgSwing.LOW.value,
        gap_fn=_bear_gap,
        kind=FvgKind.BEARISH.value,
        inv=FvgKind.BULLISH.value,
    )

    # de-dupe identical zones, newest swing first
    seen: set[tuple[float, float, int]] = set()
    uniq: list[SwingFvg] = []
    for f in sorted(found, key=lambda x: (x.swing_index, x.formed_index), reverse=True):
        key = (f.top, f.bottom, f.swing_index)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(f)
    uniq = uniq[: int(p["max_fvgs"])]

    active = [f for f in uniq if f.state != FvgState.BREACHED.value]
    above = min((f for f in active if f.bottom > last), key=lambda f: f.bottom - last, default=None)
    below = max((f for f in active if f.top < last), key=lambda f: f.top - last, default=None)
    inside = next((f for f in active if f.bottom <= last <= f.top), None)

    nearest = inside or (
        min((f for f in (above, below) if f), key=lambda f: abs(f.distance_pct), default=None)
    )
    bias = nearest.inversion_kind if nearest else "NEUTRAL"

    return FvgScan(
        fvgs=uniq,
        last_price=round(last, 2),
        nearest_above=above,
        nearest_below=below,
        bias=bias,
        bars_scanned=n - start,
    )
