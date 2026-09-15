"""RSI — Wilder, with deterministic terminal-value precedence + divergence (docs/05 §4)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from analytical_core.enums import AnalysisScope, AnalysisStatus, Divergence, RSIState
from analytical_core.indicators._common import DP_RSI, build_result, insufficient, rnd
from analytical_core.params import effective_params
from analytical_core.results import AnalysisResult
from analytical_core.series import OHLCVSeries

_KEY = "rsi"
_SCOPE = AnalysisScope.PER_TIMEFRAME


def _wilder_rsi(source: Sequence[float], period: int) -> list[float | None]:
    n = len(source)
    out: list[float | None] = [None] * n
    if n < period + 1:
        return out
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, n):
        d = source[i] - source[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    out[period] = _rsi_from(avg_gain, avg_loss)
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out[i + 1] = _rsi_from(avg_gain, avg_loss)
    return out


def _rsi_from(avg_gain: float, avg_loss: float) -> float:
    # exact precedence per docs/05 §4
    if avg_gain == 0.0 and avg_loss == 0.0:
        return 50.0
    if avg_loss == 0.0:
        return 100.0
    if avg_gain == 0.0:
        return 0.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def _divergence(
    close: Sequence[float], rsi_vals: Sequence[float | None], lookback: int, min_delta: float
) -> Divergence:
    if len(close) < lookback:
        return Divergence.NONE
    w_close = close[-lookback:]
    w_rsi = rsi_vals[-lookback:]
    if any(v is None for v in w_rsi):
        return Divergence.NONE
    lo = min(w_close)
    hi = max(w_close)
    if close[-1] == lo:
        argmin = w_close.index(lo)  # earliest on ties
        if w_rsi[-1] - w_rsi[argmin] >= min_delta:  # type: ignore[operator]
            return Divergence.BULLISH
    if close[-1] == hi:
        argmax = w_close.index(hi)
        if w_rsi[argmax] - w_rsi[-1] >= min_delta:  # type: ignore[operator]
            return Divergence.BEARISH
    return Divergence.NONE


def rsi(series: OHLCVSeries, overrides: Mapping[str, Any] | None = None) -> AnalysisResult:
    p = effective_params(_KEY, overrides)
    period = int(p["period"])
    as_of = series.ts[-1] if len(series) else None
    window = (series.ts[0] if len(series) else None, as_of)

    if len(series) < period + 1:
        return insufficient(
            analysis_key=_KEY,
            scope=_SCOPE,
            as_of_ts=as_of or _epoch(),
            reason=f"need >= {period + 1} bars, have {len(series)}",
            overrides=overrides,
            bars_used=len(series),
            coverage_ratio=series.coverage_ratio,
            last_bar_final=series.last_bar_final,
        )

    close = series.close
    rsi_vals = _wilder_rsi(close, period)
    cur = rsi_vals[-1]
    assert cur is not None
    prev = rsi_vals[-2]

    if cur >= 70.0:
        state = RSIState.OVERBOUGHT
    elif cur <= 30.0:
        state = RSIState.OVERSOLD
    else:
        state = RSIState.NEUTRAL

    slope = None if prev is None else rnd(cur - prev, DP_RSI)
    div = _divergence(close, rsi_vals, int(p["div_lookback"]), float(p["div_min_rsi_delta"]))

    return build_result(
        analysis_key=_KEY,
        scope=_SCOPE,
        status=AnalysisStatus.OK,
        as_of_ts=as_of,
        values={
            "rsi": rnd(cur, DP_RSI),
            "state": state.value,
            "slope": slope,
            "divergence": div.value,
        },
        series={"rsi": [rnd(v, DP_RSI) for v in rsi_vals]},
        overrides=overrides,
        input_window=window,
        bars_used=len(series),
        coverage_ratio=series.coverage_ratio,
        warmup_ok=len(series) >= period * 5,
        last_bar_final=series.last_bar_final,
    )


def _epoch() -> datetime:
    from datetime import UTC

    return datetime(1970, 1, 1, tzinfo=UTC)
