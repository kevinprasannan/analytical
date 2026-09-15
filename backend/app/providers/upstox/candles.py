"""Upstox v3 candle adapter — M1 + D1 only (Phase 2.3 + live INGEST).

M5/M15/H1 are **not** fetched from the provider (docs/11 PV-2 branch
``AGGREGATE_FROM_M1``); asking for one raises
:class:`ProviderUnavailableCapabilityError`. Aggregation from persisted M1 is
2.4.

Prior days come from the **historical** endpoint (closed bars); the current IST
trading day comes from the **intraday** endpoint. They share the 7-element row
shape, so both go through the same :func:`normalize_candle`. The *last* intraday
bar is marked ``is_final=False`` (it may still be forming) so the ingestion
watermark stops just short of it and the repair pass re-verifies it next cycle.

Guarantees (user Phase-2 data-integrity rules, docs/05 §3.4):
* an empty provider ``candles`` array yields ``[]`` — never a synthesised bar;
* interior gaps are preserved;
* every ``ts`` comes from the provider payload, normalised to bar-open UTC;
* OI is element 7 as-sent (``None`` when absent), never zero-filled.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from analytical_core.enums import Timeframe
from app.providers.base import (
    OHLCVBar,
    OIPoint,
    ProviderError,
    ProviderUnavailableCapabilityError,
)
from app.providers.upstox.capabilities import UPSTOX_CAPABILITIES
from app.providers.upstox.endpoints import historical_candle_path, intraday_candle_path
from app.providers.upstox.http import UpstoxHTTPClient
from app.providers.upstox.normalize import IST, UpstoxCandleFormatError, normalize_candle

_UNIT_INTERVAL: dict[Timeframe, tuple[str, str]] = {
    Timeframe.M1: ("minutes", "1"),
    Timeframe.D1: ("days", "1"),
}


def _require_supported(timeframe: Timeframe) -> tuple[str, str]:
    try:
        return _UNIT_INTERVAL[timeframe]
    except KeyError:
        raise ProviderUnavailableCapabilityError(
            f"Upstox candle adapter serves only {sorted(t.value for t in _UNIT_INTERVAL)}; "
            f"{timeframe.value} is aggregated from M1 (docs/11 PV-2)."
        ) from None


def _date_chunks(start: date, end: date, max_days: int) -> list[tuple[date, date]]:
    if start > end:
        raise ValueError(f"start date {start} is after end date {end}")
    span = max(1, max_days)
    out: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(end, cursor + timedelta(days=span - 1))
        out.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return out


def _extract_candles(body: dict, path: str) -> list:
    data = body.get("data")
    if not isinstance(data, dict) or "candles" not in data:
        raise UpstoxCandleFormatError(f"Upstox response for {path} has no data.candles array.")
    candles = data["candles"]
    if not isinstance(candles, list):
        raise UpstoxCandleFormatError(f"Upstox data.candles for {path} is not a list.")
    return candles


def fetch_candles(
    client: UpstoxHTTPClient,
    *,
    instrument_key: str,
    timeframe: Timeframe,
    start: datetime,
    end: datetime,
    api_version: str,
    is_bar_close: bool = False,
    source: str,
    now: datetime | None = None,
) -> list[OHLCVBar]:
    unit, interval = _require_supported(timeframe)
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start/end must be tz-aware")
    start_d = start.astimezone(IST).date()
    end_d = end.astimezone(IST).date()
    today = (now or datetime.now(tz=UTC)).astimezone(IST).date()
    max_days = UPSTOX_CAPABILITIES.max_range_days.get(timeframe.value, 31)

    by_ts: dict[datetime, OHLCVBar] = {}

    # --- prior days: historical endpoint (closed bars) --------------------
    hist_end = min(end_d, today - timedelta(days=1))
    if start_d <= hist_end:
        for from_d, to_d in _date_chunks(start_d, hist_end, max_days):
            path = historical_candle_path(
                api_version=api_version,
                instrument_key=instrument_key,
                unit=unit,
                interval=interval,
                to_date=to_d.isoformat(),
                from_date=from_d.isoformat(),
            )
            body = client.get_json(path)
            for row in _extract_candles(body, path):
                bar = normalize_candle(
                    row, timeframe, is_final=True, source=source, is_bar_close=is_bar_close
                )
                by_ts.setdefault(bar.ts, bar)  # first chunk wins at a seam

    # --- current trading day: intraday endpoint -------------------------
    if start_d <= today <= end_d:
        path = intraday_candle_path(
            api_version=api_version,
            instrument_key=instrument_key,
            unit=unit,
            interval=interval,
        )
        body = client.get_json(path)
        intraday = [
            normalize_candle(
                row,
                timeframe,
                is_final=True,
                source=f"{source}/intraday",
                is_bar_close=is_bar_close,
            )
            for row in _extract_candles(body, path)
        ]
        intraday.sort(key=lambda b: b.ts)
        if intraday:  # the most recent intraday bar may still be forming
            intraday[-1] = replace(intraday[-1], is_final=False)
        for bar in intraday:
            by_ts[bar.ts] = bar  # intraday wins for today

    return [by_ts[ts] for ts in sorted(by_ts)]


def fetch_oi_points(
    client: UpstoxHTTPClient,
    *,
    instrument_key: str,
    timeframe: Timeframe,
    start: datetime,
    end: datetime,
    api_version: str,
    is_bar_close: bool = False,
    source: str,
    now: datetime | None = None,
) -> list[OIPoint]:
    """Per-candle OI, projected 1:1 from the same candle response (docs/03 §5.2).

    Rows without element 7 (e.g. an INDEX instrument) contribute nothing, so an
    index request yields ``[]`` rather than a fabricated series.
    """
    bars = fetch_candles(
        client,
        instrument_key=instrument_key,
        timeframe=timeframe,
        start=start,
        end=end,
        api_version=api_version,
        is_bar_close=is_bar_close,
        source=source,
        now=now,
    )
    return [
        OIPoint(ts=b.ts, oi=int(b.open_interest), provider_oi_change=None, source=b.source)
        for b in bars
        if b.open_interest is not None
    ]


__all__ = [
    "fetch_candles",
    "fetch_oi_points",
    "ProviderError",
    "UpstoxCandleFormatError",
]
