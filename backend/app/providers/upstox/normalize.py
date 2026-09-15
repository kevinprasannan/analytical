"""Pure normalisation for Upstox v3 candle rows (Phase 2.3).

No IO, no HTTP, no config reads — takes a raw candle row + timeframe, returns a
provider-neutral :class:`~app.providers.base.OHLCVBar` with a **bar-open, tz-aware
UTC** timestamp (docs/03 §2, docs/05 §3.2, docs/11 PV-7).

Upstox v3 candle row (docs/11 §4 PV-2/PV-4, 2026-08-27)::

    [ts_iso, open, high, low, close, volume, open_interest]

* ``ts_iso`` is ISO 8601 with a ``+05:30`` offset and is **candle-start**
  (bar-open). A ``B_SNAPSHOT``-style provider that returned bar-close would be
  handled by ``is_bar_close=True`` (subtract one interval) — off by default.
* element 7 (OI) is present for F&O; an INDEX row (or a 6-element row) has none →
  ``open_interest=None``. Never zero-filled or fabricated here.
* ``D1`` rows are re-anchored to the NSE session-open instant for the trading
  date (default 09:15 IST → 03:45:00Z, docs/05 §3.3).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from analytical_core.enums import Timeframe
from app.providers.base import OHLCVBar, ProviderError

IST = ZoneInfo("Asia/Kolkata")

#: default NSE continuous session open (docs/05 §3.1). A shortened `NORMAL` day
#: overrides this from `market_calendar` — wired in a later sub-step.
DEFAULT_SESSION_OPEN_IST = time(9, 15)

_INTERVAL: dict[Timeframe, timedelta] = {
    Timeframe.M1: timedelta(minutes=1),
    Timeframe.M5: timedelta(minutes=5),
    Timeframe.M15: timedelta(minutes=15),
    Timeframe.H1: timedelta(hours=1),
}


class UpstoxCandleFormatError(ProviderError):
    """A candle row / response did not match the documented Upstox v3 shape."""


def interval_delta(tf: Timeframe) -> timedelta:
    try:
        return _INTERVAL[tf]
    except KeyError:  # pragma: no cover - guarded by callers
        raise UpstoxCandleFormatError(f"no fixed interval for timeframe {tf.value}") from None


def _dec(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise UpstoxCandleFormatError(f"non-numeric price field: {value!r}") from exc


def parse_iso_ts(raw: object) -> datetime:
    """Parse an Upstox ISO-8601 timestamp. Must be timezone-aware — we never
    guess an offset."""
    if not isinstance(raw, str):
        raise UpstoxCandleFormatError(f"candle timestamp is not a string: {raw!r}")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise UpstoxCandleFormatError(f"unparseable candle timestamp: {raw!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise UpstoxCandleFormatError(f"candle timestamp has no timezone offset: {raw!r}")
    return parsed


def session_open_utc(trading_date: date, open_ist: time = DEFAULT_SESSION_OPEN_IST) -> datetime:
    """The NSE session-open instant for ``trading_date`` as bar-open UTC."""
    return datetime.combine(trading_date, open_ist, tzinfo=IST).astimezone(UTC)


def candle_ts_to_bar_open_utc(raw: object, tf: Timeframe, *, is_bar_close: bool) -> datetime:
    """Normalise one candle timestamp to bar-open UTC for the given timeframe."""
    parsed = parse_iso_ts(raw)
    if tf is Timeframe.D1:
        # a daily bar is anchored to the session open of its IST trading date;
        # bar-close vs bar-open does not move that anchor.
        return session_open_utc(parsed.astimezone(IST).date())
    if is_bar_close:
        parsed = parsed - interval_delta(tf)
    return parsed.astimezone(UTC)


def _oi(row: Sequence[object]) -> int | None:
    if len(row) < 7 or row[6] is None:
        return None
    try:
        return int(row[6])
    except (TypeError, ValueError) as exc:
        raise UpstoxCandleFormatError(f"non-integer open_interest: {row[6]!r}") from exc


def normalize_candle(
    row: Sequence[object],
    tf: Timeframe,
    *,
    is_final: bool,
    source: str,
    is_bar_close: bool = False,
) -> OHLCVBar:
    if not isinstance(row, Sequence) or isinstance(row, str | bytes) or len(row) < 6:
        raise UpstoxCandleFormatError(f"candle row is not a >=6-element array: {row!r}")
    try:
        volume = int(row[5])
    except (TypeError, ValueError) as exc:
        raise UpstoxCandleFormatError(f"non-integer volume: {row[5]!r}") from exc
    return OHLCVBar(
        ts=candle_ts_to_bar_open_utc(row[0], tf, is_bar_close=is_bar_close),
        open=_dec(row[1]),
        high=_dec(row[2]),
        low=_dec(row[3]),
        close=_dec(row[4]),
        volume=volume,
        is_final=is_final,
        source=source,
        open_interest=_oi(row),
    )
