"""Open Interest — deterministic change + epsilon classification (docs/05 §9).

``provider_oi_change`` is echoed for cross-check only and is **never** used in
classification (docs/05 §9.2). The same classifier serves branch A
(PER_TIMEFRAME) and branch B (SNAPSHOT).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from analytical_core.enums import (
    AnalysisStatus,
    Direction,
    InstrumentType,
    OIBehavior,
)
from analytical_core.indicators._common import (
    DP_PRICE,
    DP_RATIO,
    build_result,
    insufficient,
    not_applicable,
    rnd,
)
from analytical_core.params import effective_params
from analytical_core.results import AnalysisResult
from analytical_core.series import OpenInterestSeries

_KEY = "open_interest"
_OPTION_WARNING = (
    "labels describe positioning in this option contract, not the underlying (docs/05 §9.5)"
)


def _direction(delta: float, eps: float) -> Direction:
    if delta > eps:
        return Direction.UP
    if delta < -eps:
        return Direction.DOWN
    return Direction.FLAT


def classify_oi_behavior(price_dir: Direction, oi_dir: Direction) -> OIBehavior:
    """Price direction × OI direction → the positioning label (docs/05 §9)."""
    if price_dir is Direction.FLAT or oi_dir is Direction.FLAT:
        return OIBehavior.INDETERMINATE
    table = {
        (Direction.UP, Direction.UP): OIBehavior.LONG_BUILDUP,
        (Direction.DOWN, Direction.UP): OIBehavior.SHORT_BUILDUP,
        (Direction.DOWN, Direction.DOWN): OIBehavior.LONG_UNWINDING,
        (Direction.UP, Direction.DOWN): OIBehavior.SHORT_COVERING,
    }
    return table[(price_dir, oi_dir)]


def open_interest(
    series: OpenInterestSeries,
    *,
    instrument_type: InstrumentType,
    overrides: Mapping[str, Any] | None = None,
) -> AnalysisResult:
    p = effective_params(_KEY, overrides)
    lookback = int(p["change_lookback"])
    price_eps_pct = float(p["price_epsilon_pct"])
    oi_eps_pct = float(p["oi_epsilon_pct"])
    oi_eps_abs = float(p["oi_eps_abs"])
    scope = series.scope
    n = len(series)
    as_of = series.ts[-1] if n else _epoch()
    window = (series.ts[0] if n else None, series.ts[-1] if n else None)

    if instrument_type is InstrumentType.INDEX:
        return not_applicable(
            analysis_key=_KEY,
            scope=scope,
            as_of_ts=as_of,
            reason="index instruments have no open interest",
            overrides=overrides,
        )
    warnings = (_OPTION_WARNING,) if instrument_type is InstrumentType.OPTION else ()

    if n < lookback + 1:
        return insufficient(
            analysis_key=_KEY,
            scope=scope,
            as_of_ts=as_of,
            reason=f"need >= {lookback + 1} points, have {n}",
            overrides=overrides,
            bars_used=n,
            last_bar_final=series.last_bar_final,
        )

    k = n - 1
    prev = k - lookback
    oi_now, oi_prev = series.oi[k], series.oi[prev]
    px_now, px_prev = series.price[k], series.price[prev]

    oi_change = oi_now - oi_prev
    price_change = px_now - px_prev
    price_eps = price_eps_pct * abs(px_prev)
    oi_eps = max(oi_eps_pct * abs(oi_prev), oi_eps_abs)

    price_dir = _direction(price_change, price_eps)
    oi_dir = _direction(float(oi_change), oi_eps)
    behavior = classify_oi_behavior(price_dir, oi_dir)

    oi_pct_change = None if oi_prev == 0 else oi_change / oi_prev
    price_pct_change = None if px_prev == 0 else price_change / px_prev
    provider_oi_change = (
        series.provider_oi_change[k] if series.provider_oi_change is not None else None
    )

    return build_result(
        analysis_key=_KEY,
        scope=scope,
        status=AnalysisStatus.OK,
        as_of_ts=as_of,
        values={
            "oi": int(oi_now),
            "oi_change": int(oi_change),
            "oi_pct_change": rnd(oi_pct_change, DP_RATIO),
            "price_change": rnd(price_change, DP_PRICE),
            "price_pct_change": rnd(price_pct_change, DP_RATIO),
            "price_direction": price_dir.value,
            "oi_direction": oi_dir.value,
            "behavior": behavior.value,
            "provider_oi_change": provider_oi_change,
        },
        warnings=warnings,
        overrides=overrides,
        input_window=window,
        bars_used=n,
        last_bar_final=series.last_bar_final,
    )


def _epoch() -> datetime:
    from datetime import UTC

    return datetime(1970, 1, 1, tzinfo=UTC)
