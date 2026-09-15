"""Upstox v3 candle endpoint path builders (Phase 2.3 / live INGEST).

Two candle endpoints, same 7-element row shape (``[ts, o, h, l, c, volume, oi]``):

* **historical** — closed bars for prior days::

      GET /{ver}/historical-candle/{instrument_key}/{unit}/{interval}/{to_date}/{from_date}

* **intraday** — the *current* trading day's bars (up to the last completed
  candle); no date args::

      GET /{ver}/historical-candle/intraday/{instrument_key}/{unit}/{interval}

The candle adapter (`candles.py`) fetches the current IST trading day from
``intraday`` and everything before it from ``historical``, then merges.
"""

from __future__ import annotations

from urllib.parse import quote


def historical_candle_path(
    *,
    api_version: str,
    instrument_key: str,
    unit: str,
    interval: str,
    to_date: str,
    from_date: str,
) -> str:
    ik = quote(instrument_key, safe="")
    return f"/{api_version}/historical-candle/{ik}/{unit}/{interval}/{to_date}/{from_date}"


def intraday_candle_path(
    *,
    api_version: str,
    instrument_key: str,
    unit: str,
    interval: str,
) -> str:
    ik = quote(instrument_key, safe="")
    return f"/{api_version}/historical-candle/intraday/{ik}/{unit}/{interval}"


# -- realtime quote endpoints (docs/07 §4.10) ----------------------------
#: LTP / OHLC / option-greek are v3; the full quote is v2 only.
MARKET_QUOTE_LTP = "/v3/market-quote/ltp"
MARKET_QUOTE_OHLC = "/v3/market-quote/ohlc"
MARKET_QUOTE_FULL = "/v2/market-quote/quotes"
MARKET_QUOTE_OPTION_GREEK = "/v3/market-quote/option-greek"

#: max ``instrument_key`` values per request (Upstox docs).
QUOTE_CHUNK = 500
OPTION_GREEK_CHUNK = 50
