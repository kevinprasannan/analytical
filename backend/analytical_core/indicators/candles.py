"""Major candlestick patterns (docs/05 §9b).

Pure and deterministic. Scans the last ``scan_bars`` finished bars for a fixed
set of well-known one/two/three-bar patterns, tags each `BULLISH` / `BEARISH` /
`NEUTRAL` with a strength and the short-term trend it appeared in, and reports
the most recent one as `last_pattern` + `bias`. Descriptive labels — no
BUY/SELL, no entry / target / stop.

A candidate bar preceded by a run of >= ``frozen_run_min_bars`` exactly flat,
identical bars is skipped rather than scored (see ``_frozen_tape_artifact``) —
a provider feed carrying the same LTP forward for several bars and then
jumping in one step is not a genuine candle.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from analytical_core.enums import AnalysisScope, AnalysisStatus, CandleBias, CandleStrength
from analytical_core.indicators._common import DP_PRICE, build_result, insufficient, rnd
from analytical_core.params import effective_params
from analytical_core.results import AnalysisResult
from analytical_core.series import OHLCVSeries

_KEY = "candles"
_SCOPE = AnalysisScope.PER_TIMEFRAME

_BULL = CandleBias.BULLISH.value
_BEAR = CandleBias.BEARISH.value
_NEUT = CandleBias.NEUTRAL.value
_W, _M, _S = CandleStrength.WEAK.value, CandleStrength.MODERATE.value, CandleStrength.STRONG.value


class _Bar:
    __slots__ = ("o", "h", "l", "c", "ts")

    def __init__(self, o: float, h: float, low: float, c: float, ts: datetime) -> None:
        self.o, self.h, self.l, self.c, self.ts = o, h, low, c, ts

    @property
    def body(self) -> float:
        return abs(self.c - self.o)

    @property
    def rng(self) -> float:
        return self.h - self.l

    @property
    def upper(self) -> float:
        return self.h - max(self.o, self.c)

    @property
    def lower(self) -> float:
        return min(self.o, self.c) - self.l

    @property
    def bull(self) -> bool:
        return self.c > self.o

    @property
    def bear(self) -> bool:
        return self.c < self.o

    @property
    def mid(self) -> float:
        return (self.o + self.c) / 2.0


def _frozen_tape_artifact(bars: list[_Bar], i: int, min_run: int) -> bool:
    """True when bar ``i`` looks like a provider feed snapshot resuming after a
    stall, not a genuine candle: its own range is non-zero, but it is preceded
    by a run of >= ``min_run`` bars that are all exactly flat (open == high ==
    low == close) and identical to each other and to bar ``i``'s open — i.e.
    the quote was carried forward unchanged for several bars and then jumped in
    one step. Seen in practice on the NSE_INDEX intraday feed most trading days
    in the last ~15 minutes before the close (every M1 print pinned to the same
    LTP for 10+ minutes, then a single-bar catch-up to the real close) — a
    provider artifact, not organic price discovery (hard rule 11: no bar is
    fabricated or carried forward for a no-trade interval)."""
    if min_run <= 0 or i < min_run or bars[i].rng <= 0:
        return False
    frozen_value = bars[i - 1]
    if frozen_value.rng > 0 or frozen_value.o != bars[i].o:
        return False
    run = 0
    for j in range(i - 1, -1, -1):
        b = bars[j]
        if b.rng > 0 or b.o != frozen_value.o:
            break
        run += 1
    return run >= min_run


def _trend(closes: tuple[float, ...], end: int, lookback: int) -> str:
    """Short-term trend of the bars *before* ``end`` (the pattern's last bar)."""
    a = end - 1 - lookback
    if a < 0:
        return "SIDEWAYS"
    ref, now = closes[a], closes[end - 1]
    if ref == 0:
        return "SIDEWAYS"
    chg = (now - ref) / ref
    if chg <= -0.0015:
        return "DOWNTREND"
    if chg >= 0.0015:
        return "UPTREND"
    return "SIDEWAYS"


def _one_bar(b: _Bar, p: Mapping[str, Any], trend: str):
    rng = b.rng
    if rng <= 0:
        return None
    body_pct = b.body / rng
    # doji family — a tiny body, sub-classed by which wick dominates. Since
    # upper + body + lower == rng and body <= doji_body_pct * rng, the two
    # wicks cannot both be "small" (opp_wick_pct * rng) at once, so at most
    # one of the two branches below fires.
    if body_pct <= float(p["doji_body_pct"]):
        small_upper_d = b.upper <= float(p["opp_wick_pct"]) * rng
        small_lower_d = b.lower <= float(p["opp_wick_pct"]) * rng
        if small_lower_d and not small_upper_d:
            # open/close pinned near the low, long upper wick — rejection at
            # highs; a reversal read confirmed by an uptrend context
            return ("GRAVESTONE_DOJI", _BEAR, _S if trend == "UPTREND" else _W)
        if small_upper_d and not small_lower_d:
            # mirror — rejection at lows
            return ("DRAGONFLY_DOJI", _BULL, _S if trend == "DOWNTREND" else _W)
        return ("DOJI", _NEUT, _W if trend == "SIDEWAYS" else _M)
    # marubozu
    if body_pct >= float(p["marubozu_body_pct"]):
        return ("MARUBOZU", _BULL if b.bull else _BEAR, _S)
    long_lower = b.lower >= float(p["wick_body_mult"]) * b.body
    long_upper = b.upper >= float(p["wick_body_mult"]) * b.body
    small_upper = b.upper <= float(p["opp_wick_pct"]) * rng
    small_lower = b.lower <= float(p["opp_wick_pct"]) * rng
    small_body = body_pct <= float(p["star_body_pct"])
    if long_lower and small_upper and small_body:
        # hammer family — bull reversal in a downtrend, bear (hanging man) in an uptrend
        if trend == "DOWNTREND":
            return ("HAMMER", _BULL, _S)
        if trend == "UPTREND":
            return ("HANGING_MAN", _BEAR, _M)
        return ("HAMMER", _BULL, _W)
    if long_upper and small_lower and small_body:
        if trend == "UPTREND":
            return ("SHOOTING_STAR", _BEAR, _S)
        if trend == "DOWNTREND":
            return ("INVERTED_HAMMER", _BULL, _M)
        return ("SHOOTING_STAR", _BEAR, _W)
    return None


def _two_bar(a: _Bar, b: _Bar, p: Mapping[str, Any], trend: str):
    if a.rng <= 0 or b.rng <= 0:
        return None
    # engulfing — current real body fully covers the prior real body, opposite colour
    if a.bear and b.bull and b.o <= a.c and b.c >= a.o and b.body > a.body:
        return ("BULLISH_ENGULFING", _BULL, _S if trend == "DOWNTREND" else _M)
    if a.bull and b.bear and b.o >= a.c and b.c <= a.o and b.body > a.body:
        return ("BEARISH_ENGULFING", _BEAR, _S if trend == "UPTREND" else _M)
    # harami — small current body contained within a large prior body, opposite colour
    contain = min(a.o, a.c) < min(b.o, b.c) and max(b.o, b.c) < max(a.o, a.c)
    if a.bear and b.bull and contain and a.body >= 2.0 * b.body:
        return ("BULLISH_HARAMI", _BULL, _M if trend == "DOWNTREND" else _W)
    if a.bull and b.bear and contain and a.body >= 2.0 * b.body:
        return ("BEARISH_HARAMI", _BEAR, _M if trend == "UPTREND" else _W)
    # piercing line — after a bearish bar, a bullish bar opening below and closing
    # back above the prior midpoint (but under the prior open)
    if a.bear and b.bull and b.o < a.c and a.mid < b.c < a.o:
        return ("PIERCING_LINE", _BULL, _S if trend == "DOWNTREND" else _M)
    if a.bull and b.bear and b.o > a.c and a.o < b.c < a.mid:
        return ("DARK_CLOUD_COVER", _BEAR, _S if trend == "UPTREND" else _M)
    return None


def _three_bar(a: _Bar, mid: _Bar, c: _Bar, p: Mapping[str, Any], trend: str):
    # a zero-range middle bar (e.g. a stale/frozen print) is not a "star" —
    # a real star has a small body *within some real range*, not a null bar.
    if a.rng <= 0 or c.rng <= 0 or mid.rng <= 0:
        return None
    star = mid.body <= float(p["star_body_pct"]) * mid.rng
    if a.bear and star and c.bull and c.c > a.mid and c.body >= 0.6 * a.body:
        return ("MORNING_STAR", _BULL, _S)
    if a.bull and star and c.bear and c.c < a.mid and c.body >= 0.6 * a.body:
        return ("EVENING_STAR", _BEAR, _S)
    return None


def candles(series: OHLCVSeries, overrides: Mapping[str, Any] | None = None) -> AnalysisResult:
    p = effective_params(_KEY, overrides)
    scan = int(p["scan_bars"])
    tl = int(p["trend_lookback"])
    n = len(series)
    as_of = series.ts[-1] if n else datetime(1970, 1, 1, tzinfo=UTC)
    window = (series.ts[0] if n else None, series.ts[-1] if n else None)
    need = scan + tl + 3
    if n < need:
        return insufficient(
            analysis_key=_KEY,
            scope=_SCOPE,
            as_of_ts=as_of,
            reason=f"need >= {need} bars, have {n}",
            overrides=overrides,
            bars_used=n,
            coverage_ratio=series.coverage_ratio,
            last_bar_final=series.last_bar_final,
        )

    bars = [
        _Bar(
            float(series.open[i]),
            float(series.high[i]),
            float(series.low[i]),
            float(series.close[i]),
            series.ts[i],
        )
        for i in range(n)
    ]

    frozen_run_min = int(p["frozen_run_min_bars"])
    found: list[dict[str, Any]] = []
    for i in range(n - scan, n):  # each bar in the scan window as the pattern's last bar
        if _frozen_tape_artifact(bars, i, frozen_run_min):
            continue
        trend = _trend(series.close, i, tl)
        hit = (
            _three_bar(bars[i - 2], bars[i - 1], bars[i], p, trend)
            or _two_bar(bars[i - 1], bars[i], p, trend)
            or _one_bar(bars[i], p, trend)
        )
        if hit is None:
            continue
        name, bias, strength = hit
        found.append(
            {
                "pattern": name,
                "bias": bias,
                "strength": strength,
                "trend_context": trend,
                "bar_ts": bars[i].ts.isoformat(),
                "bars_ago": n - 1 - i,
                "open": rnd(bars[i].o, DP_PRICE),
                "high": rnd(bars[i].h, DP_PRICE),
                "low": rnd(bars[i].l, DP_PRICE),
                "close": rnd(bars[i].c, DP_PRICE),
            }
        )

    found.sort(key=lambda x: x["bars_ago"])  # most recent first
    last = found[0] if found else None
    n_bull = sum(1 for f in found if f["bias"] == _BULL)
    n_bear = sum(1 for f in found if f["bias"] == _BEAR)
    bias = last["bias"] if last else _NEUT

    return build_result(
        analysis_key=_KEY,
        scope=_SCOPE,
        status=AnalysisStatus.OK,
        as_of_ts=as_of,
        values={
            "bias": bias,
            "last_pattern": last["pattern"] if last else None,
            "last_bias": last["bias"] if last else None,
            "last_strength": last["strength"] if last else None,
            "last_bars_ago": last["bars_ago"] if last else None,
            "on_last_bar": bool(last and last["bars_ago"] == 0),
            "n_bullish": n_bull,
            "n_bearish": n_bear,
            "bars_scanned": scan,
            "patterns": found,
        },
        overrides=overrides,
        input_window=window,
        bars_used=n,
        coverage_ratio=series.coverage_ratio,
        warmup_ok=n >= need,
        last_bar_final=series.last_bar_final,
    )
