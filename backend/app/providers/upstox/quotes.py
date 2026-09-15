"""Upstox v3/v2 realtime quote adapters (docs/07 §4.10).

REST snapshots — LTP, OHLC, full quote, option greeks. Read-only; never an input
to the deterministic engine. Each fetcher chunks ``instrument_key`` (Upstox caps
requests at 500, or 50 for option greeks), and re-keys the response by
``instrument_token`` (Upstox returns the map keyed by ``EXCHANGE:SYMBOL``, but
each entry carries the original ``EXCHANGE|SYMBOL`` key as ``instrument_token``).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from app.providers.base import (
    FullQuote,
    LtpQuote,
    OhlcBucket,
    OhlcQuote,
    OptionGreekQuote,
    ProviderError,
)
from app.providers.upstox import endpoints as ep
from app.providers.upstox.http import UpstoxHTTPClient


class UpstoxQuoteFormatError(ProviderError):
    """A quote response did not match the documented Upstox shape."""


def _chunks(items: Sequence[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(items), size):
        yield list(items[i : i + size])


def _dec(v: object) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def _int(v: object) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _flt(v: object) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _ts(v: object) -> datetime | None:
    """Accept an epoch (ms or s) or an ISO string."""
    if v in (None, "", 0):
        return None
    if isinstance(v, int | float):
        secs = v / 1000.0 if v > 1e11 else float(v)
        return datetime.fromtimestamp(secs, tz=UTC)
    try:
        return datetime.fromisoformat(str(v))
    except ValueError:
        return None


def _data_map(body: dict, path: str) -> dict:
    data = body.get("data")
    if not isinstance(data, dict):
        raise UpstoxQuoteFormatError(f"Upstox response for {path} has no data map.")
    return data


def _rekey(data: dict) -> dict[str, dict]:
    """Map entries by their ``instrument_token`` (the EXCHANGE|SYMBOL key),
    falling back to the dict key with ``:`` normalised to ``|``."""
    out: dict[str, dict] = {}
    for k, v in data.items():
        if not isinstance(v, dict):
            continue
        key = v.get("instrument_token") or k.replace(":", "|", 1)
        out[str(key)] = v
    return out


def _query(symbols: Sequence[str]) -> dict[str, str]:
    return {"instrument_key": ",".join(symbols)}


def _bucket(raw: object) -> OhlcBucket | None:
    if not isinstance(raw, dict):
        return None
    o, h, low, c = (_dec(raw.get(x)) for x in ("open", "high", "low", "close"))
    if None in (o, h, low, c):
        return None
    return OhlcBucket(
        open=o, high=h, low=low, close=c, volume=_int(raw.get("volume")), ts=_ts(raw.get("ts"))
    )


def fetch_ltp(
    client: UpstoxHTTPClient, provider_symbols: Sequence[str], *, source: str
) -> dict[str, LtpQuote]:
    out: dict[str, LtpQuote] = {}
    for chunk in _chunks(provider_symbols, ep.QUOTE_CHUNK):
        body = client.get_json(ep.MARKET_QUOTE_LTP, params=_query(chunk))
        for key, v in _rekey(_data_map(body, ep.MARKET_QUOTE_LTP)).items():
            lp = _dec(v.get("last_price"))
            if lp is None:
                continue
            out[key] = LtpQuote(
                provider_symbol=key,
                last_price=lp,
                last_qty=_int(v.get("ltq")),
                day_volume=_int(v.get("volume")),
                prev_close=_dec(v.get("cp")),
                source=source,
            )
    return out


def fetch_ohlc(
    client: UpstoxHTTPClient,
    provider_symbols: Sequence[str],
    *,
    interval: str = "1d",
    source: str,
) -> dict[str, OhlcQuote]:
    out: dict[str, OhlcQuote] = {}
    for chunk in _chunks(provider_symbols, ep.QUOTE_CHUNK):
        body = client.get_json(ep.MARKET_QUOTE_OHLC, params={**_query(chunk), "interval": interval})
        for key, v in _rekey(_data_map(body, ep.MARKET_QUOTE_OHLC)).items():
            out[key] = OhlcQuote(
                provider_symbol=key,
                last_price=_dec(v.get("last_price")),
                live=_bucket(v.get("live_ohlc")) or _bucket(v.get("ohlc")),
                prev=_bucket(v.get("prev_ohlc")),
                source=source,
            )
    return out


def fetch_full_quote(
    client: UpstoxHTTPClient, provider_symbols: Sequence[str], *, source: str
) -> dict[str, FullQuote]:
    out: dict[str, FullQuote] = {}
    for chunk in _chunks(provider_symbols, ep.QUOTE_CHUNK):
        body = client.get_json(ep.MARKET_QUOTE_FULL, params=_query(chunk))
        for key, v in _rekey(_data_map(body, ep.MARKET_QUOTE_FULL)).items():
            ohlc = v.get("ohlc") if isinstance(v.get("ohlc"), dict) else {}
            out[key] = FullQuote(
                provider_symbol=key,
                last_price=_dec(v.get("last_price")),
                open=_dec(ohlc.get("open")),
                high=_dec(ohlc.get("high")),
                low=_dec(ohlc.get("low")),
                close=_dec(ohlc.get("close")),
                day_volume=_int(v.get("volume")),
                average_price=_dec(v.get("average_price")),
                oi=_int(v.get("oi")),
                net_change=_dec(v.get("net_change")),
                total_buy_qty=_int(v.get("total_buy_quantity")),
                total_sell_qty=_int(v.get("total_sell_quantity")),
                lower_circuit=_dec(v.get("lower_circuit_limit")),
                upper_circuit=_dec(v.get("upper_circuit_limit")),
                ts=_ts(v.get("timestamp")),
                source=source,
            )
    return out


def fetch_option_greeks(
    client: UpstoxHTTPClient, provider_symbols: Sequence[str], *, source: str
) -> dict[str, OptionGreekQuote]:
    out: dict[str, OptionGreekQuote] = {}
    for chunk in _chunks(provider_symbols, ep.OPTION_GREEK_CHUNK):
        body = client.get_json(ep.MARKET_QUOTE_OPTION_GREEK, params=_query(chunk))
        for key, v in _rekey(_data_map(body, ep.MARKET_QUOTE_OPTION_GREEK)).items():
            out[key] = OptionGreekQuote(
                provider_symbol=key,
                last_price=_dec(v.get("last_price")),
                iv=_flt(v.get("iv") if v.get("iv") is not None else v.get("implied_volatility")),
                delta=_flt(v.get("delta")),
                gamma=_flt(v.get("gamma")),
                theta=_flt(v.get("theta")),
                vega=_flt(v.get("vega")),
                oi=_int(v.get("oi")),
                day_volume=_int(v.get("volume")),
                source=source,
            )
    return out
