"""Upstox realtime quote adapters (docs/07 §4.10) over an injected transport.

No live call is made — every test drives ``httpx.MockTransport``.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

from app.providers.upstox import quotes
from app.providers.upstox.http import UpstoxHTTPClient

TOKEN = "tok_SECRET_never_log"


def _client(responder):
    reqs: list[httpx.Request] = []

    def handle(req: httpx.Request) -> httpx.Response:
        reqs.append(req)
        return responder(req)

    c = UpstoxHTTPClient(
        base_url="https://api.upstox.com",
        token_provider=lambda: TOKEN,
        transport=httpx.MockTransport(handle),
        max_rps=0,
        sleep_fn=lambda _s: None,
    )
    return c, reqs


def _ok(data: dict):
    return lambda _req: httpx.Response(200, json={"status": "success", "data": data})


def test_ltp_rekeys_by_instrument_token_and_parses_fields():
    # Upstox keys the map by EXCHANGE:SYMBOL but each entry carries the |-key
    data = {
        "NSE_INDEX:Nifty 50": {
            "last_price": 24175.5,
            "instrument_token": "NSE_INDEX|Nifty 50",
            "ltq": 0,
            "volume": 0,
            "cp": 24090.85,
        }
    }
    client, reqs = _client(_ok(data))
    out = quotes.fetch_ltp(client, ["NSE_INDEX|Nifty 50"], source="s")
    assert set(out) == {"NSE_INDEX|Nifty 50"}
    q = out["NSE_INDEX|Nifty 50"]
    assert q.last_price == Decimal("24175.5")
    assert q.prev_close == Decimal("24090.85")
    assert "/v3/market-quote/ltp" in str(reqs[0].url)
    assert "instrument_key=NSE_INDEX" in str(reqs[0].url)


def test_ohlc_reads_live_and_prev_buckets():
    data = {
        "NSE_FO:X": {
            "last_price": 101.0,
            "instrument_token": "NSE_FO|68407",
            "live_ohlc": {
                "open": 100,
                "high": 105,
                "low": 99,
                "close": 101,
                "volume": 5000,
                "ts": 0,
            },
            "prev_ohlc": {
                "open": 98,
                "high": 102,
                "low": 97,
                "close": 100,
                "volume": 8000,
                "ts": 0,
            },
        }
    }
    client, _ = _client(_ok(data))
    out = quotes.fetch_ohlc(client, ["NSE_FO|68407"], interval="1d", source="s")
    q = out["NSE_FO|68407"]
    assert q.live.high == Decimal("105") and q.prev.close == Decimal("100")
    assert q.live.volume == 5000


def test_full_quote_parses_ohlc_oi_and_circuit_limits():
    data = {
        "NSE_FO:Y": {
            "instrument_token": "NSE_FO|68407",
            "last_price": 101.0,
            "ohlc": {"open": 100, "high": 105, "low": 99, "close": 101},
            "volume": 123456,
            "average_price": 100.7,
            "oi": 250000,
            "net_change": 1.15,
            "total_buy_quantity": 900,
            "total_sell_quantity": 1100,
            "lower_circuit_limit": 90.0,
            "upper_circuit_limit": 110.0,
            "timestamp": "2026-08-31T10:30:00+05:30",
        }
    }
    client, _ = _client(_ok(data))
    q = quotes.fetch_full_quote(client, ["NSE_FO|68407"], source="s")["NSE_FO|68407"]
    assert q.open == Decimal("100") and q.close == Decimal("101")
    assert q.oi == 250000
    assert q.lower_circuit == Decimal("90.0") and q.upper_circuit == Decimal("110.0")
    assert q.ts is not None


def test_option_greeks_parses_iv_and_greeks():
    data = {
        "NSE_FO:Z": {
            "instrument_token": "NSE_FO|OPTKEY",
            "last_price": 120.5,
            "iv": 0.1423,
            "delta": 0.55,
            "gamma": 0.002,
            "theta": -3.1,
            "vega": 8.4,
            "oi": 42000,
            "volume": 15000,
        }
    }
    client, _ = _client(_ok(data))
    q = quotes.fetch_option_greeks(client, ["NSE_FO|OPTKEY"], source="s")["NSE_FO|OPTKEY"]
    assert q.iv == pytest.approx(0.1423)
    assert q.delta == pytest.approx(0.55)
    assert q.oi == 42000


def test_ltp_chunks_requests_over_500_keys():
    calls: list[int] = []

    def responder(req: httpx.Request) -> httpx.Response:
        n = str(req.url).count("NSE_EQ")
        calls.append(n)
        return httpx.Response(200, json={"status": "success", "data": {}})

    client, reqs = _client(responder)
    keys = [f"NSE_EQ|{i}" for i in range(1101)]
    quotes.fetch_ltp(client, keys, source="s")
    assert len(reqs) == 3  # 500 + 500 + 101
    assert calls == [500, 500, 101]


def test_missing_data_map_is_format_error():
    client, _ = _client(lambda _req: httpx.Response(200, json={"status": "success"}))
    with pytest.raises(quotes.UpstoxQuoteFormatError):
        quotes.fetch_ltp(client, ["NSE_INDEX|Nifty 50"], source="s")
