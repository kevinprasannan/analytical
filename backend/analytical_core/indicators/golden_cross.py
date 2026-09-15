"""Golden Cross — SMA/EMA fast/slow, deterministic cross scan (docs/05 §7).

Primarily an INDEX / Daily analysis. On a dated FUTURE/OPTION it is
``NOT_APPLICABLE`` unless ``enable_for_dated`` is set, in which case every result
carries a warning that it is not equivalent to the index golden cross.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from analytical_core.enums import (
    AnalysisScope,
    AnalysisStatus,
    GoldenCrossType,
    InstrumentType,
)
from analytical_core.indicators._common import (
    DP_MA,
    DP_RATIO,
    build_result,
    ema_series,
    insufficient,
    not_applicable,
    rnd,
    rolling_sma,
)
from analytical_core.params import effective_params
from analytical_core.results import AnalysisResult
from analytical_core.series import OHLCVSeries

_KEY = "golden_cross"
_SCOPE = AnalysisScope.PER_TIMEFRAME
_DATED = frozenset({InstrumentType.FUTURE, InstrumentType.OPTION})
_DATED_WARNING = "computed on a dated-contract series; not equivalent to the index golden cross"
_NA_REASON = (
    "dated contract history shorter than slow_period; index trend is represented "
    "by the INDEX instrument"
)


def _ma(xs: Sequence[float], period: int, kind: str) -> list[float | None]:
    return ema_series(xs, period) if kind.upper() == "EMA" else rolling_sma(xs, period)


def golden_cross(
    series: OHLCVSeries,
    *,
    instrument_type: InstrumentType,
    overrides: Mapping[str, Any] | None = None,
) -> AnalysisResult:
    p = effective_params(_KEY, overrides)
    fast_p = int(p["fast_period"])
    slow_p = int(p["slow_period"])
    ma_type = str(p["ma_type"])
    search = int(p["cross_search_window"])
    recent_window = int(p["recent_window"])
    enable_for_dated = bool(p["enable_for_dated"])
    n = len(series)
    as_of = series.ts[-1] if n else _epoch()
    window = (series.ts[0] if n else None, series.ts[-1] if n else None)

    if instrument_type in _DATED and not enable_for_dated:
        return not_applicable(
            analysis_key=_KEY, scope=_SCOPE, as_of_ts=as_of, reason=_NA_REASON, overrides=overrides
        )
    warnings = (_DATED_WARNING,) if instrument_type in _DATED else ()

    if n < slow_p + 1:
        return insufficient(
            analysis_key=_KEY,
            scope=_SCOPE,
            as_of_ts=as_of,
            reason=f"need >= {slow_p + 1} bars, have {n}",
            overrides=overrides,
            bars_used=n,
            coverage_ratio=series.coverage_ratio,
            last_bar_final=series.last_bar_final,
        )

    close = series.close
    fast = _ma(close, fast_p, ma_type)
    slow = _ma(close, slow_p, ma_type)

    def _sign(i: int) -> int:
        f, s = fast[i], slow[i]
        if f is None or s is None:
            return 0
        return (f > s) - (f < s)

    look = min(search, n)
    carried = 0
    cross_type = GoldenCrossType.NONE_IN_WINDOW
    cross_ts: datetime | None = None
    cross_idx: int | None = None
    for i in range(n - look, n):
        s = _sign(i)
        if s == 0:
            continue
        if carried != 0 and s != carried:
            if carried < 0 < s:
                cross_type, cross_ts, cross_idx = GoldenCrossType.GOLDEN, series.ts[i], i
            else:
                cross_type, cross_ts, cross_idx = GoldenCrossType.DEATH, series.ts[i], i
        carried = s

    bars_since = None if cross_idx is None else (n - 1 - cross_idx)
    state = "ABOVE" if (fast[-1] or 0) > (slow[-1] or 0) else "BELOW"
    separation = ((fast[-1] - slow[-1]) / slow[-1]) if slow[-1] else 0.0  # type: ignore[operator]
    recent = bars_since is not None and bars_since <= recent_window
    provisional = cross_idx is not None and cross_idx == n - 1 and not series.last_bar_final

    return build_result(
        analysis_key=_KEY,
        scope=_SCOPE,
        status=AnalysisStatus.OK,
        as_of_ts=as_of,
        values={
            "fast": rnd(fast[-1], DP_MA),
            "slow": rnd(slow[-1], DP_MA),
            "state": state,
            "cross_type": cross_type.value,
            "cross_ts": cross_ts.isoformat() if cross_ts else None,
            "bars_since_cross": bars_since,
            "separation": rnd(separation, DP_RATIO),
            "recent": recent,
            "provisional": provisional,
        },
        warnings=warnings,
        overrides=overrides,
        input_window=window,
        bars_used=n,
        coverage_ratio=series.coverage_ratio,
        warmup_ok=n >= slow_p * 2,
        last_bar_final=series.last_bar_final,
        provisional=provisional,
    )


def _epoch() -> datetime:
    from datetime import UTC

    return datetime(1970, 1, 1, tzinfo=UTC)
