"""Volume — MA, RVOL, spike, up/down mix, OLS trend (docs/05 §8).

Structural guard: ``has_volume=False`` -> ``NOT_APPLICABLE``. ``has_volume=True``
but zero traded volume in the window -> ``INSUFFICIENT_DATA`` (so an instrument
expected to have volume still incurs the scoring confidence penalty).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from analytical_core.enums import (
    AnalysisScope,
    AnalysisStatus,
    VolumeTrend,
    VolumeUpDownState,
)
from analytical_core.indicators._common import (
    DP_MA,
    DP_RATIO,
    build_result,
    insufficient,
    not_applicable,
    ols_slope,
    rnd,
    sma,
)
from analytical_core.params import effective_params
from analytical_core.results import AnalysisResult
from analytical_core.series import OHLCVSeries

_KEY = "volume"
_SCOPE = AnalysisScope.PER_TIMEFRAME


def volume(
    series: OHLCVSeries,
    *,
    has_volume: bool,
    overrides: Mapping[str, Any] | None = None,
) -> AnalysisResult:
    p = effective_params(_KEY, overrides)
    ma_period = int(p["ma_period"])
    spike_mult = float(p["spike_mult"])
    rvol_lookback = int(p["rvol_lookback"])
    flat_eps_pct = float(p["trend_flat_eps_pct"])
    n = len(series)
    as_of = series.ts[-1] if n else _epoch()
    window = (series.ts[0] if n else None, series.ts[-1] if n else None)

    if not has_volume:
        return not_applicable(
            analysis_key=_KEY,
            scope=_SCOPE,
            as_of_ts=as_of,
            reason="instrument/provider has no volume",
            overrides=overrides,
        )

    need = max(ma_period, rvol_lookback + 1)
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

    vol = [float(v) for v in series.volume]
    if sum(vol[-ma_period:]) == 0.0:
        return insufficient(
            analysis_key=_KEY,
            scope=_SCOPE,
            as_of_ts=as_of,
            reason="no traded volume in window",
            overrides=overrides,
            bars_used=n,
            coverage_ratio=series.coverage_ratio,
            last_bar_final=series.last_bar_final,
        )

    vol_ma = sma(vol, ma_period)
    denom_window = vol[-1 - rvol_lookback : -1]
    denom = sum(denom_window) / len(denom_window) if denom_window else 0.0
    rvol = None if denom == 0.0 else vol[-1] / denom
    spike = vol[-1] >= spike_mult * vol_ma

    up = sum(1 for i in range(n - ma_period, n) if series.close[i] >= series.open[i])
    down = ma_period - up
    if down == 0:
        up_down_ratio = None
        ud_state = VolumeUpDownState.ALL_UP
    elif up == 0:
        up_down_ratio = 0.0
        ud_state = VolumeUpDownState.ALL_DOWN
    else:
        up_down_ratio = up / down
        if up > down:
            ud_state = VolumeUpDownState.MORE_UP
        elif down > up:
            ud_state = VolumeUpDownState.MORE_DOWN
        else:
            ud_state = VolumeUpDownState.BALANCED

    slope = ols_slope(vol[-ma_period:])
    eps = flat_eps_pct * vol_ma
    if slope > eps:
        trend = VolumeTrend.RISING
    elif slope < -eps:
        trend = VolumeTrend.FALLING
    else:
        trend = VolumeTrend.FLAT

    price_change_pct_recent = series.close[-1] / series.close[-1 - rvol_lookback] - 1.0

    return build_result(
        analysis_key=_KEY,
        scope=_SCOPE,
        status=AnalysisStatus.OK,
        as_of_ts=as_of,
        values={
            "volume": int(series.volume[-1]),
            "vol_ma": rnd(vol_ma, DP_MA),
            "rvol": rnd(rvol, DP_RATIO),
            "spike": bool(spike),
            "up_down_ratio": rnd(up_down_ratio, DP_RATIO),
            "up_down_state": ud_state.value,
            "trend": trend.value,
        },
        aux={"price_change_pct_recent": rnd(price_change_pct_recent, DP_RATIO)},
        overrides=overrides,
        input_window=window,
        bars_used=n,
        coverage_ratio=series.coverage_ratio,
        warmup_ok=n >= need,
        last_bar_final=series.last_bar_final,
    )


def _epoch() -> datetime:
    from datetime import UTC

    return datetime(1970, 1, 1, tzinfo=UTC)
