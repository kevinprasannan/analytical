"""Shared numeric helpers + the provenance-carrying result builder (docs/05 §1–§2)."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from analytical_core.enums import AnalysisScope, AnalysisStatus
from analytical_core.params import effective_params, params_hash, params_id
from analytical_core.results import AnalysisResult
from analytical_core.versioning import ALGO_VERSION

# rounding policy (docs/05 §2), applied once at result construction
DP_PRICE = 4
DP_RSI = 2
DP_RATIO = 6
DP_MA = 4


def sma(xs: Sequence[float], period: int) -> float:
    if period <= 0 or len(xs) < period:
        raise ValueError("sma: not enough data")
    return math.fsum(xs[-period:]) / period


def rolling_sma(xs: Sequence[float], period: int) -> list[float | None]:
    """SMA at each index; ``None`` until ``period`` values are available."""
    out: list[float | None] = []
    for i in range(len(xs)):
        if i + 1 < period:
            out.append(None)
        else:
            out.append(math.fsum(xs[i + 1 - period : i + 1]) / period)
    return out


def ema_series(xs: Sequence[float], period: int) -> list[float | None]:
    """EMA with an SMA seed at index ``period-1`` (docs/05 §6)."""
    if period <= 0:
        raise ValueError("ema_series: period must be > 0")
    out: list[float | None] = [None] * len(xs)
    if len(xs) < period:
        return out
    k = 2.0 / (period + 1)
    prev = math.fsum(xs[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(xs)):
        prev = xs[i] * k + prev * (1.0 - k)
        out[i] = prev
    return out


def population_stdev(xs: Sequence[float], ddof: int = 0) -> float:
    n = len(xs)
    if n - ddof <= 0:
        raise ValueError("population_stdev: not enough data for ddof")
    mean = math.fsum(xs) / n
    var = math.fsum((x - mean) ** 2 for x in xs) / (n - ddof)
    return math.sqrt(var)


def ols_slope(xs: Sequence[float]) -> float:
    """Least-squares slope of ``xs`` against index 0..n-1."""
    n = len(xs)
    if n < 2:
        return 0.0
    xbar = (n - 1) / 2.0
    ybar = math.fsum(xs) / n
    num = math.fsum((i - xbar) * (xs[i] - ybar) for i in range(n))
    den = math.fsum((i - xbar) ** 2 for i in range(n))
    return num / den if den else 0.0


def wilder_atr(
    high: Sequence[float], low: Sequence[float], close: Sequence[float], period: int
) -> float | None:
    """Wilder ATR over the whole series; ``None`` if fewer than ``period + 1`` bars."""
    n = len(close)
    if n < period + 1:
        return None
    trs: list[float] = []
    for i in range(1, n):
        tr = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
        trs.append(tr)
    atr = math.fsum(trs[:period]) / period
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
    return atr


def rnd(x: float | None, dp: int) -> float | None:
    if x is None:
        return None
    if not math.isfinite(x):
        return None
    return round(x, dp)


def build_result(
    *,
    analysis_key: str,
    scope: AnalysisScope,
    status: AnalysisStatus,
    as_of_ts: datetime,
    values: Mapping[str, Any],
    aux: Mapping[str, Any] | None = None,
    series: Mapping[str, Any] | None = None,
    warnings: Sequence[str] = (),
    overrides: Mapping[str, Any] | None = None,
    input_window: tuple[datetime | None, datetime | None] = (None, None),
    bars_used: int | None = None,
    coverage_ratio: float | None = None,
    warmup_ok: bool | None = None,
    last_bar_final: bool | None = None,
    provisional: bool = False,
) -> AnalysisResult:
    eff = effective_params(analysis_key, overrides)
    meta: dict[str, Any] = {
        "algo_version": ALGO_VERSION,
        "params_id": params_id(analysis_key),
        "params_hash": params_hash(eff),
        "params": eff,
        "input_window_start": _iso(input_window[0]),
        "input_window_end": _iso(input_window[1]),
        "bars_used": bars_used,
        "coverage_ratio": coverage_ratio,
        "warmup_ok": warmup_ok,
        "last_bar_final": last_bar_final,
        "provisional": provisional,
    }
    return AnalysisResult(
        analysis_key=analysis_key,
        scope=scope,
        status=status,
        as_of_ts=as_of_ts,
        values=dict(values),
        aux=dict(aux or {}),
        series=dict(series) if series is not None else None,
        warnings=tuple(warnings),
        meta=meta,
    )


def insufficient(
    *,
    analysis_key: str,
    scope: AnalysisScope,
    as_of_ts: datetime,
    reason: str,
    overrides: Mapping[str, Any] | None = None,
    bars_used: int | None = None,
    coverage_ratio: float | None = None,
    last_bar_final: bool | None = None,
) -> AnalysisResult:
    return build_result(
        analysis_key=analysis_key,
        scope=scope,
        status=AnalysisStatus.INSUFFICIENT_DATA,
        as_of_ts=as_of_ts,
        values={"reason": reason},
        overrides=overrides,
        bars_used=bars_used,
        coverage_ratio=coverage_ratio,
        warmup_ok=False,
        last_bar_final=last_bar_final,
    )


def not_applicable(
    *,
    analysis_key: str,
    scope: AnalysisScope,
    as_of_ts: datetime,
    reason: str,
    warnings: Sequence[str] = (),
    overrides: Mapping[str, Any] | None = None,
) -> AnalysisResult:
    return build_result(
        analysis_key=analysis_key,
        scope=scope,
        status=AnalysisStatus.NOT_APPLICABLE,
        as_of_ts=as_of_ts,
        values={"reason": reason},
        warnings=warnings,
        overrides=overrides,
    )


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None
