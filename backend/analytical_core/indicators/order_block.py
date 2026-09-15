"""Order blocks — last opposing candle before a Break of Structure (docs/05 §9a).

Pure and deterministic. Fractal swing detection → the first later bar to *close*
beyond a swing (a Break of Structure) → the order block is the last opposing
candle before that break, if the impulse out of it clears a volatility gate.
Active blocks are aged out and marked mitigated once price trades back in. The
result names a net structural ``bias``, where price sits relative to the nearest
blocks (``zone_state``), and the block zones themselves — analytical only, no
BUY/SELL, no entry/target/stop.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from analytical_core.enums import (
    AnalysisScope,
    AnalysisStatus,
    OrderBlockBias,
    OrderBlockZoneState,
)
from analytical_core.indicators._common import DP_PRICE, DP_RATIO, build_result, insufficient, rnd, wilder_atr
from analytical_core.params import effective_params
from analytical_core.results import AnalysisResult
from analytical_core.series import OHLCVSeries

_KEY = "order_block"
_SCOPE = AnalysisScope.PER_TIMEFRAME


def _swings(values: Sequence[float], lookback: int, *, high: bool) -> list[int]:
    """Fractal swing indices: ``i`` where ``values[i]`` is the strict extreme of
    ``[i-lookback, i+lookback]``. Needs ``lookback`` bars on each side."""
    out: list[int] = []
    n = len(values)
    for i in range(lookback, n - lookback):
        v = values[i]
        window = values[i - lookback : i + lookback + 1]
        if high:
            if v == max(window) and window.count(v) == 1:
                out.append(i)
        else:
            if v == min(window) and window.count(v) == 1:
                out.append(i)
    return out


def _zone(series: OHLCVSeries, idx: int, mode: str) -> tuple[float, float]:
    o, c = series.open[idx], series.close[idx]
    if mode == "body":
        return (min(o, c), max(o, c))
    return (series.low[idx], series.high[idx])  # "range"


def _mitigated_at(
    series: OHLCVSeries, lo: float, hi: float, after: int, mode: str
) -> datetime | None:
    """First bar strictly after ``after`` to trade back into ``[lo, hi]``."""
    for k in range(after + 1, len(series)):
        if mode == "close":
            if lo <= series.close[k] <= hi:
                return series.ts[k]
        elif series.low[k] <= hi and series.high[k] >= lo:
            return series.ts[k]
    return None


def _proximity(distance_pct: float, age_bars: int, dist_k_pct: float, age_full: int) -> float:
    """0..1 — how much an unmitigated block should weigh: closer + fresher = more."""
    near = max(0.0, 1.0 - abs(distance_pct) / dist_k_pct) if dist_k_pct > 0 else 0.0
    fresh = max(0.0, 1.0 - age_bars / age_full) if age_full > 0 else 0.0
    return near * fresh


def order_block(series: OHLCVSeries, overrides: Mapping[str, Any] | None = None) -> AnalysisResult:
    p = effective_params(_KEY, overrides)
    swing_lookback = int(p["swing_lookback"])
    atr_period = int(p["atr_period"])
    impulse_min_atr = float(p["impulse_min_atr"])
    bos_search = int(p["bos_search_window"])
    max_age = int(p["max_ob_age_bars"])
    zone_mode = str(p["zone"])
    mit_mode = str(p["mitigation"])

    n = len(series)
    as_of = series.ts[-1] if n else datetime(1970, 1, 1, tzinfo=UTC)
    window = (series.ts[0] if n else None, series.ts[-1] if n else None)
    need = swing_lookback * 2 + bos_search + atr_period + 1
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

    atr = wilder_atr(series.high, series.low, series.close, atr_period)
    last = n - 1
    price = series.close[-1]

    zones: list[dict[str, Any]] = []

    def _scan(swings: list[int], *, bullish: bool) -> None:
        for s in swings:
            level = series.high[s] if bullish else series.low[s]
            j = None
            for k in range(s + 1, min(n, s + 1 + bos_search)):
                if (bullish and series.close[k] > level) or (
                    not bullish and series.close[k] < level
                ):
                    j = k
                    break
            if j is None:
                continue
            # the last opposing candle in [s, j): bearish for a bullish OB
            ob = None
            for k in range(j - 1, s - 1, -1):
                down = series.close[k] < series.open[k]
                if (bullish and down) or (not bullish and not down):
                    ob = k
                    break
            if ob is None:  # degenerate — take the extreme candle of the run
                ob = min(range(s, j), key=lambda k: series.low[k]) if bullish else max(
                    range(s, j), key=lambda k: series.high[k]
                )
            lo, hi = _zone(series, ob, zone_mode)
            impulse = (series.high[j] - lo) if bullish else (hi - series.low[j])
            if atr and impulse < impulse_min_atr * atr:
                continue
            mit_ts = _mitigated_at(series, lo, hi, j, mit_mode)
            age = last - j
            if age > max_age:
                continue
            side = "BULLISH" if bullish else "BEARISH"
            if lo <= price <= hi:
                dist = 0.0
            elif bullish:
                dist = (price - hi) / price * 100.0  # +ve: price above a demand OB
            else:
                dist = (lo - price) / price * 100.0  # +ve: price below a supply OB
            zones.append(
                {
                    "side": side,
                    "low": rnd(lo, DP_PRICE),
                    "high": rnd(hi, DP_PRICE),
                    "mid": rnd((lo + hi) / 2.0, DP_PRICE),
                    "formed_ts": series.ts[ob].isoformat(),
                    "bos_ts": series.ts[j].isoformat(),
                    "age_bars": age,
                    "mitigated": mit_ts is not None,
                    "mitigated_ts": mit_ts.isoformat() if mit_ts else None,
                    "distance_pct": rnd(dist, DP_RATIO),
                }
            )

    _scan(_swings(series.high, swing_lookback, high=True), bullish=True)
    _scan(_swings(series.low, swing_lookback, high=False), bullish=False)
    # newest first, de-dup identical zones (a level can be broken twice)
    zones.sort(key=lambda z: (z["bos_ts"], z["formed_ts"]), reverse=True)
    seen: set[tuple] = set()
    uniq: list[dict[str, Any]] = []
    for z in zones:
        k = (z["side"], z["low"], z["high"])
        if k not in seen:
            seen.add(k)
            uniq.append(z)
    zones = uniq

    active_bull = [z for z in zones if z["side"] == "BULLISH" and not z["mitigated"]]
    active_bear = [z for z in zones if z["side"] == "BEARISH" and not z["mitigated"]]
    nearest_bull = min(active_bull, key=lambda z: abs(z["distance_pct"]), default=None)
    nearest_bear = min(active_bear, key=lambda z: abs(z["distance_pct"]), default=None)

    # zone_state considers *every* recent block (mitigated or not): "price inside
    # a supply/demand block" is the tag/reaction moment, which is also what
    # mitigates a fresh one.
    in_bull = next((z for z in zones if z["side"] == "BULLISH" and z["low"] <= price <= z["high"]), None)
    in_bear = next((z for z in zones if z["side"] == "BEARISH" and z["low"] <= price <= z["high"]), None)
    if in_bull is not None and in_bear is None:
        zone_state = OrderBlockZoneState.IN_BULLISH
    elif in_bear is not None and in_bull is None:
        zone_state = OrderBlockZoneState.IN_BEARISH
    elif in_bull is not None and in_bear is not None:
        zone_state = (
            OrderBlockZoneState.IN_BULLISH
            if in_bull["bos_ts"] >= in_bear["bos_ts"]
            else OrderBlockZoneState.IN_BEARISH
        )
    else:
        zone_state = OrderBlockZoneState.OUTSIDE

    if zone_state is OrderBlockZoneState.IN_BULLISH:
        bias = OrderBlockBias.BULLISH
    elif zone_state is OrderBlockZoneState.IN_BEARISH:
        bias = OrderBlockBias.BEARISH
    elif nearest_bull is not None and nearest_bear is None:
        bias = OrderBlockBias.BULLISH
    elif nearest_bear is not None and nearest_bull is None:
        bias = OrderBlockBias.BEARISH
    elif nearest_bull is not None and nearest_bear is not None:
        bias = (
            OrderBlockBias.BULLISH
            if abs(nearest_bull["distance_pct"]) < abs(nearest_bear["distance_pct"])
            else OrderBlockBias.BEARISH
        )
    else:
        bias = OrderBlockBias.NEUTRAL

    return build_result(
        analysis_key=_KEY,
        scope=_SCOPE,
        status=AnalysisStatus.OK,
        as_of_ts=as_of,
        values={
            "bias": bias.value,
            "zone_state": zone_state.value,
            "price": rnd(price, DP_PRICE),
            "atr": rnd(atr, DP_PRICE),
            "n_active_bullish": len(active_bull),
            "n_active_bearish": len(active_bear),
            "nearest_bullish": nearest_bull,
            "nearest_bearish": nearest_bear,
            "zones": zones,
        },
        overrides=overrides,
        input_window=window,
        bars_used=n,
        coverage_ratio=series.coverage_ratio,
        warmup_ok=n >= need,
        last_bar_final=series.last_bar_final,
    )
