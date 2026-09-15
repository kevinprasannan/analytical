"""7 EMA + slope + Wilder-ATR / close-stdev auxiliaries for scoring (docs/05 §6)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from analytical_core.enums import AnalysisScope, AnalysisStatus, MASlopeState
from analytical_core.indicators._common import (
    DP_MA,
    DP_PRICE,
    DP_RATIO,
    build_result,
    ema_series,
    insufficient,
    population_stdev,
    rnd,
    wilder_atr,
)
from analytical_core.params import effective_params
from analytical_core.results import AnalysisResult
from analytical_core.series import OHLCVSeries

_KEY = "ema7"
_SCOPE = AnalysisScope.PER_TIMEFRAME


def ema7(series: OHLCVSeries, overrides: Mapping[str, Any] | None = None) -> AnalysisResult:
    p = effective_params(_KEY, overrides)
    period = int(p["period"])
    slope_lookback = int(p["slope_lookback"])
    flat_eps_pct = float(p["slope_flat_eps_pct"])
    atr_period = int(p["atr_period"])
    n = len(series)
    as_of = series.ts[-1] if n else _epoch()
    window = (series.ts[0] if n else None, series.ts[-1] if n else None)

    if n < period:
        return insufficient(
            analysis_key=_KEY,
            scope=_SCOPE,
            as_of_ts=as_of,
            reason=f"need >= {period} bars, have {n}",
            overrides=overrides,
            bars_used=n,
            coverage_ratio=series.coverage_ratio,
            last_bar_final=series.last_bar_final,
        )

    close = series.close
    ema_vals = ema_series(close, period)
    cur = ema_vals[-1]
    assert cur is not None

    slope: float | None = None
    slope_state = MASlopeState.UNKNOWN
    if n >= period + slope_lookback and ema_vals[-1 - slope_lookback] is not None:
        slope = cur - ema_vals[-1 - slope_lookback]  # type: ignore[operator]
        eps = flat_eps_pct * cur
        if slope > eps:
            slope_state = MASlopeState.RISING
        elif slope < -eps:
            slope_state = MASlopeState.FALLING
        else:
            slope_state = MASlopeState.FLAT

    atr14 = wilder_atr(series.high, series.low, close, atr_period)
    stdev_n = slope_lookback * 5
    close_stdev_n = (
        population_stdev(close[-stdev_n:], ddof=0) if n >= stdev_n and stdev_n >= 2 else None
    )

    return build_result(
        analysis_key=_KEY,
        scope=_SCOPE,
        status=AnalysisStatus.OK,
        as_of_ts=as_of,
        values={
            "ema": rnd(cur, DP_MA),
            "price_vs_ema": rnd(close[-1] - cur, DP_PRICE),
            "price_above": bool(close[-1] > cur),
            "slope": rnd(slope, DP_MA),
            "slope_state": slope_state.value,
        },
        aux={
            "atr14": rnd(atr14, DP_PRICE),
            "close_stdev_n": rnd(close_stdev_n, DP_RATIO),
        },
        series={"ema": [rnd(v, DP_MA) for v in ema_vals]},
        overrides=overrides,
        input_window=window,
        bars_used=n,
        coverage_ratio=series.coverage_ratio,
        warmup_ok=n >= period + slope_lookback,
        last_bar_final=series.last_bar_final,
    )


def _epoch() -> datetime:
    from datetime import UTC

    return datetime(1970, 1, 1, tzinfo=UTC)
