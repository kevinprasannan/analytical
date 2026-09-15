"""Bollinger Bands — population std, squeeze/percentile exclude the current bar (docs/05 §5)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from analytical_core.enums import AnalysisScope, AnalysisStatus, BollingerPosition
from analytical_core.indicators._common import (
    DP_MA,
    DP_RATIO,
    build_result,
    insufficient,
    population_stdev,
    rnd,
    sma,
)
from analytical_core.params import effective_params
from analytical_core.results import AnalysisResult
from analytical_core.series import OHLCVSeries

_KEY = "bollinger"
_SCOPE = AnalysisScope.PER_TIMEFRAME


def _bandwidth_at(
    close: tuple[float, ...], end: int, period: int, num_std: float, ddof: int
) -> float:
    window = close[end - period : end]
    basis = sum(window) / period
    dev = population_stdev(window, ddof=ddof)
    upper = basis + num_std * dev
    lower = basis - num_std * dev
    return 0.0 if upper == lower else (upper - lower) / basis


def bollinger(series: OHLCVSeries, overrides: Mapping[str, Any] | None = None) -> AnalysisResult:
    p = effective_params(_KEY, overrides)
    period = int(p["period"])
    num_std = float(p["num_std"])
    ddof = int(p["std_ddof"])
    squeeze_lookback = int(p["squeeze_lookback"])
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
    src = close[-period:]
    basis = sma(close, period)
    dev = population_stdev(src, ddof=ddof)
    upper = basis + num_std * dev
    lower = basis - num_std * dev
    degenerate = upper == lower

    if degenerate:
        percent_b = 0.5
        bandwidth = 0.0
        position = BollingerPosition.MIDDLE
    else:
        percent_b = (close[-1] - lower) / (upper - lower)
        bandwidth = (upper - lower) / basis
        if close[-1] >= upper:
            position = BollingerPosition.ABOVE_UPPER
        elif close[-1] <= lower:
            position = BollingerPosition.BELOW_LOWER
        elif close[-1] >= basis:
            position = BollingerPosition.UPPER_HALF
        else:
            position = BollingerPosition.LOWER_HALF

    # prior bandwidth window: the `squeeze_lookback` values BEFORE the current bar
    prior: list[float] = []
    for end in range(n - 1, period - 1, -1):
        if len(prior) >= squeeze_lookback:
            break
        prior.append(_bandwidth_at(close, end, period, num_std, ddof))
    prior.reverse()

    squeeze: bool | None = None
    bandwidth_percentile: float | None = None
    if len(prior) >= squeeze_lookback:
        squeeze = bandwidth <= min(prior)
        bandwidth_percentile = sum(1 for b in prior if b < bandwidth) / len(prior)

    return build_result(
        analysis_key=_KEY,
        scope=_SCOPE,
        status=AnalysisStatus.OK,
        as_of_ts=as_of,
        values={
            "basis": rnd(basis, DP_MA),
            "upper": rnd(upper, DP_MA),
            "lower": rnd(lower, DP_MA),
            "percent_b": rnd(percent_b, DP_RATIO),
            "bandwidth": rnd(bandwidth, DP_RATIO),
            "bandwidth_percentile": rnd(bandwidth_percentile, DP_RATIO),
            "squeeze": squeeze,
            "position": position.value,
        },
        overrides=overrides,
        input_window=window,
        bars_used=n,
        coverage_ratio=series.coverage_ratio,
        warmup_ok=n >= period + squeeze_lookback,
        last_bar_final=series.last_bar_final,
    )


def _epoch() -> datetime:
    from datetime import UTC

    return datetime(1970, 1, 1, tzinfo=UTC)
