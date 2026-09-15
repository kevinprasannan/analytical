"""Phase 2.3 — Upstox v3 candle adapter (M1 + D1) over an injected transport.

No live Upstox call is ever made: every test drives ``httpx.MockTransport``
(docs/09 §1.5, §2.9).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from analytical_core.enums import Timeframe
from app.config import Settings
from app.providers.base import (
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderUnavailableCapabilityError,
)
from app.providers.upstox import UpstoxProvider, candles
from app.providers.upstox.http import RateLimiter, UpstoxHTTPClient
from app.providers.upstox.normalize import UpstoxCandleFormatError

TOKEN = "tok_SECRET_never_log_0987654321"
START = datetime(2026, 8, 27, 0, 0, tzinfo=UTC)
END = datetime(2026, 8, 27, 23, 59, tzinfo=UTC)
# 2026-08-31 11:30 IST — a moment inside the current trading day for the
# intraday-vs-historical split tests.
NOW = datetime(2026, 8, 31, 6, 0, tzinfo=UTC)


def _candle(ts_iso: str, *, oi: int | None = 0, o=100, h=101, low=99, c=100.5, v=1000):
    row = [ts_iso, o, h, low, c, v]
    if oi is not None:
        row.append(oi)
    return row


class Recorder:
    """A MockTransport handler that records requests and replays queued responses."""

    def __init__(self, responder):
        self.requests: list[httpx.Request] = []
        self._responder = responder
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._responder(request, len(self.requests) - 1)


def _client(responder, **kw) -> tuple[UpstoxHTTPClient, Recorder]:
    rec = Recorder(responder)
    defaults = dict(
        base_url="https://api.upstox.com",
        token_provider=lambda: TOKEN,
        transport=rec.transport,
        max_rps=0,  # disable spacing so injected sleeps are only backoff
        sleep_fn=lambda _s: None,
    )
    defaults.update(kw)
    return UpstoxHTTPClient(**defaults), rec


def _provider(responder, **kw) -> tuple[UpstoxProvider, Recorder]:
    client, rec = _client(responder, **kw)
    settings = Settings(active_provider="upstox", upstox_access_token="envtok")
    return UpstoxProvider(settings, http_client=client), rec


def _ok(candles):
    return lambda _req, _i: httpx.Response(
        200, json={"status": "success", "data": {"candles": candles}}
    )


# --------------------------------------------------------------------------------------
# happy paths
# --------------------------------------------------------------------------------------


def test_fetch_ohlcv_m1_orders_ascending_and_carries_oi():
    # Upstox returns newest-first
    resp = _ok(
        [
            _candle("2026-08-27T09:17:00+05:30", oi=56000),
            _candle("2026-08-27T09:16:00+05:30", oi=55000),
            _candle("2026-08-27T09:15:00+05:30", oi=54000),
        ]
    )
    provider, rec = _provider(resp)
    bars = provider.fetch_ohlcv("NSE_FO|68407", Timeframe.M1, START, END)

    assert [b.ts for b in bars] == [
        datetime(2026, 8, 27, 3, 45, tzinfo=UTC),
        datetime(2026, 8, 27, 3, 46, tzinfo=UTC),
        datetime(2026, 8, 27, 3, 47, tzinfo=UTC),
    ]
    assert [b.open_interest for b in bars] == [54000, 55000, 56000]
    assert all(b.is_final for b in bars)
    assert all(b.source == "upstox:v3/historical-candle" for b in bars)
    assert all(b.source != "STUB_FIXTURE" for b in bars)
    assert isinstance(bars[0].open, Decimal)
    # request shape: minutes/1, instrument key percent-encoded
    assert "/v3/historical-candle/NSE_FO%7C68407/minutes/1/" in str(rec.requests[0].url)
    assert rec.requests[0].headers["Authorization"] == f"Bearer {TOKEN}"


def _split_responder(hist, intra):
    def r(req, _i):
        body = intra if "/historical-candle/intraday/" in str(req.url) else hist
        return httpx.Response(200, json={"status": "success", "data": {"candles": body}})

    return r


def test_current_day_uses_intraday_endpoint_and_marks_last_bar_forming():
    hist = [_candle("2026-08-28T09:15:00+05:30", oi=100)]
    intra = [  # newest-first, as Upstox returns
        _candle("2026-08-31T09:17:00+05:30", oi=133),
        _candle("2026-08-31T09:16:00+05:30", oi=132),
        _candle("2026-08-31T09:15:00+05:30", oi=131),
    ]
    client, rec = _client(_split_responder(hist, intra))
    bars = candles.fetch_candles(
        client,
        instrument_key="NSE_FO|68407",
        timeframe=Timeframe.M1,
        start=datetime(2026, 8, 28, 0, 0, tzinfo=UTC),
        end=NOW,
        api_version="v3",
        source="upstox:v3/historical-candle",
        now=NOW,
    )
    urls = [str(r.url) for r in rec.requests]
    assert any(
        "/historical-candle/NSE_FO%7C68407/minutes/1/2026-08-30/2026-08-28" in u for u in urls
    )
    assert any("/historical-candle/intraday/NSE_FO%7C68407/minutes/1" in u for u in urls)

    assert [b.ts for b in bars] == [
        datetime(2026, 8, 28, 3, 45, tzinfo=UTC),
        datetime(2026, 8, 31, 3, 45, tzinfo=UTC),
        datetime(2026, 8, 31, 3, 46, tzinfo=UTC),
        datetime(2026, 8, 31, 3, 47, tzinfo=UTC),
    ]
    assert [b.is_final for b in bars] == [True, True, True, False]  # last intraday bar forming
    assert bars[0].source == "upstox:v3/historical-candle"
    assert bars[-1].source == "upstox:v3/historical-candle/intraday"
    assert bars[-1].open_interest == 133


def test_window_entirely_in_the_past_makes_no_intraday_call():
    client, rec = _client(_split_responder([_candle("2026-08-27T09:15:00+05:30")], []))
    candles.fetch_candles(
        client,
        instrument_key="NSE_INDEX|Nifty 50",
        timeframe=Timeframe.M1,
        start=datetime(2026, 8, 26, 0, 0, tzinfo=UTC),
        end=datetime(2026, 8, 28, 0, 0, tzinfo=UTC),
        api_version="v3",
        source="s",
        now=NOW,
    )
    assert all("/intraday/" not in str(r.url) for r in rec.requests)


def test_today_only_window_skips_the_historical_endpoint():
    client, rec = _client(_split_responder([], [_candle("2026-08-31T09:15:00+05:30", oi=5)]))
    bars = candles.fetch_candles(
        client,
        instrument_key="NSE_FO|68407",
        timeframe=Timeframe.M1,
        start=NOW,
        end=NOW,
        api_version="v3",
        source="s",
        now=NOW,
    )
    assert len(rec.requests) == 1
    assert "/historical-candle/intraday/" in str(rec.requests[0].url)
    assert bars and bars[-1].is_final is False


def test_fetch_ohlcv_d1_uses_days_unit_and_session_anchor():
    resp = _ok([_candle("2026-08-27T00:00:00+05:30", oi=0)])
    provider, rec = _provider(resp)
    bars = provider.fetch_ohlcv("NSE_INDEX|Nifty 50", Timeframe.D1, START, END)
    assert bars[0].ts == datetime(2026, 8, 27, 3, 45, tzinfo=UTC)
    assert "/days/1/" in str(rec.requests[0].url)


def test_index_rows_without_element7_have_no_oi_and_oi_series_is_empty():
    resp = _ok(
        [
            _candle("2026-08-27T09:16:00+05:30", oi=None),
            _candle("2026-08-27T09:15:00+05:30", oi=None),
        ]
    )
    provider, _ = _provider(resp)
    bars = provider.fetch_ohlcv("NSE_INDEX|Nifty 50", Timeframe.M1, START, END)
    assert [b.open_interest for b in bars] == [None, None]
    assert provider.fetch_oi_series("NSE_INDEX|Nifty 50", Timeframe.M1, START, END) == []


def test_oi_series_projects_one_to_one_with_candles():
    resp = _ok(
        [
            _candle("2026-08-27T09:16:00+05:30", oi=55000),
            _candle("2026-08-27T09:15:00+05:30", oi=54000),
        ]
    )
    provider, _ = _provider(resp)
    pts = provider.fetch_oi_series("NSE_FO|68407", Timeframe.M1, START, END)
    assert [(p.ts, p.oi) for p in pts] == [
        (datetime(2026, 8, 27, 3, 45, tzinfo=UTC), 54000),
        (datetime(2026, 8, 27, 3, 46, tzinfo=UTC), 55000),
    ]
    assert all(p.provider_oi_change is None for p in pts)


# --------------------------------------------------------------------------------------
# no fabrication
# --------------------------------------------------------------------------------------


def test_empty_candles_array_yields_empty_list():
    provider, _ = _provider(_ok([]))
    assert provider.fetch_ohlcv("NSE_FO|68407", Timeframe.M1, START, END) == []


def test_interior_gap_is_preserved_not_filled():
    # 09:15, 09:16, then a gap, then 09:19 — 4 missing? no: adapter returns exactly
    # what the provider sent, in order.
    resp = _ok(
        [
            _candle("2026-08-27T09:19:00+05:30", oi=3),
            _candle("2026-08-27T09:16:00+05:30", oi=2),
            _candle("2026-08-27T09:15:00+05:30", oi=1),
        ]
    )
    provider, _ = _provider(resp)
    bars = provider.fetch_ohlcv("NSE_FO|68407", Timeframe.M1, START, END)
    assert [b.ts.minute for b in bars] == [45, 46, 49]  # gap at :47/:48 stays a gap
    assert len(bars) == 3


# --------------------------------------------------------------------------------------
# window chunking
# --------------------------------------------------------------------------------------


def test_large_m1_window_is_split_and_concatenated_deduped():
    wide_start = datetime(2026, 1, 1, tzinfo=UTC)
    wide_end = datetime(2026, 3, 31, tzinfo=UTC)  # 90 days > 31-day M1 cap

    def responder(request: httpx.Request, i: int) -> httpx.Response:
        # each chunk returns a candle keyed to its from_date + one shared seam candle
        parts = str(request.url).split("/")
        from_date = parts[-1]
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "candles": [
                        _candle(f"{from_date}T09:16:00+05:30", oi=i),
                        _candle("2026-02-01T09:15:00+05:30", oi=99),  # duplicate ts across chunks
                    ]
                },
            },
        )

    provider, rec = _provider(responder)
    bars = provider.fetch_ohlcv("NSE_FO|68407", Timeframe.M1, wide_start, wide_end)

    assert len(rec.requests) >= 3  # 90d / 31d
    ts_list = [b.ts for b in bars]
    assert ts_list == sorted(ts_list)
    assert len(ts_list) == len(set(ts_list))  # seam duplicate collapsed


def test_from_and_to_dates_are_ist_calendar_dates_of_the_window():
    provider, rec = _provider(_ok([]))
    # 06:00Z–09:00Z on the 27th = 11:30–14:30 IST, same IST day
    provider.fetch_ohlcv(
        "NSE_FO|68407",
        Timeframe.M1,
        datetime(2026, 8, 27, 6, 0, tzinfo=UTC),
        datetime(2026, 8, 27, 9, 0, tzinfo=UTC),
    )
    assert str(rec.requests[0].url).endswith("/2026-08-27/2026-08-27")  # to_date/from_date

    # a window whose UTC end crosses into the next IST day widens to_date
    provider2, rec2 = _provider(_ok([]))
    provider2.fetch_ohlcv(
        "NSE_FO|68407",
        Timeframe.M1,
        datetime(2026, 8, 27, 0, 0, tzinfo=UTC),
        datetime(2026, 8, 27, 23, 59, tzinfo=UTC),
    )
    assert str(rec2.requests[0].url).endswith("/2026-08-28/2026-08-27")


# --------------------------------------------------------------------------------------
# capability guard
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("tf", [Timeframe.M5, Timeframe.M15, Timeframe.H1])
def test_aggregated_timeframes_are_refused_without_a_call(tf):
    provider, rec = _provider(_ok([]))
    with pytest.raises(ProviderUnavailableCapabilityError):
        provider.fetch_ohlcv("NSE_FO|68407", tf, START, END)
    assert rec.requests == []


# --------------------------------------------------------------------------------------
# errors + retry/backoff
# --------------------------------------------------------------------------------------


def test_429_then_200_retries_with_growing_backoff():
    slept: list[float] = []

    def responder(_req, i):
        if i < 2:
            return httpx.Response(429, json={"status": "error"})
        return httpx.Response(200, json={"status": "success", "data": {"candles": []}})

    client, rec = _client(responder, backoff_base=0.5, sleep_fn=slept.append)
    provider = UpstoxProvider(
        Settings(active_provider="upstox", upstox_access_token="x"), http_client=client
    )
    assert provider.fetch_ohlcv("NSE_FO|68407", Timeframe.M1, START, END) == []
    assert len(rec.requests) == 3
    assert slept == [0.5, 1.0]  # base * 2**attempt


def test_429_honours_retry_after_header():
    def responder(_req, i):
        if i == 0:
            return httpx.Response(429, headers={"Retry-After": "7"}, json={"status": "error"})
        return httpx.Response(200, json={"status": "success", "data": {"candles": []}})

    slept: list[float] = []
    client, _ = _client(responder, sleep_fn=slept.append)
    client.get_json("/p")
    assert slept == [7.0]


def test_throttle_exhausted_raises_rate_limit_error():
    client, rec = _client(
        lambda _r, _i: httpx.Response(429, json={"status": "error"}), max_retries=2
    )
    with pytest.raises(ProviderRateLimitError):
        client.get_json("/p")
    assert len(rec.requests) == 3  # 1 + 2 retries


def test_401_maps_to_auth_error_and_hides_token():
    client, _ = _client(lambda _r, _i: httpx.Response(401, json={"status": "error"}))
    with pytest.raises(ProviderAuthError) as ei:
        client.get_json("/p")
    assert TOKEN not in str(ei.value)


def test_500_maps_to_provider_error():
    client, _ = _client(lambda _r, _i: httpx.Response(500, text="boom"))
    with pytest.raises(ProviderError):
        client.get_json("/p")


def test_status_not_success_is_provider_error():
    client, _ = _client(lambda _r, _i: httpx.Response(200, json={"status": "error", "errors": []}))
    with pytest.raises(ProviderError):
        client.get_json("/p")


def test_non_json_200_is_provider_error():
    client, _ = _client(lambda _r, _i: httpx.Response(200, text="<html>nope"))
    with pytest.raises(ProviderError):
        client.get_json("/p")


def test_missing_data_candles_is_format_error():
    provider, _ = _provider(
        lambda _r, _i: httpx.Response(200, json={"status": "success", "data": {}})
    )
    with pytest.raises(UpstoxCandleFormatError):
        provider.fetch_ohlcv("NSE_FO|68407", Timeframe.M1, START, END)


# --------------------------------------------------------------------------------------
# auth gating (no transport touched)
# --------------------------------------------------------------------------------------


def test_fetch_without_a_token_raises_before_any_http(tmp_path):
    provider = UpstoxProvider(
        Settings(active_provider="upstox", upstox_token_file=str(tmp_path / "none.json"))
    )
    with pytest.raises(ProviderAuthError):
        provider.fetch_ohlcv("NSE_FO|68407", Timeframe.M1, START, END)
    with pytest.raises(ProviderAuthError):
        provider.fetch_oi_series("NSE_FO|68407", Timeframe.M1, START, END)


# --------------------------------------------------------------------------------------
# rate limiter
# --------------------------------------------------------------------------------------


def test_rate_limiter_enforces_min_spacing_under_a_fake_clock():
    now = [0.0]
    slept: list[float] = []

    def sleep_fn(s: float) -> None:
        slept.append(s)
        now[0] += s

    rl = RateLimiter(4.0, time_fn=lambda: now[0], sleep_fn=sleep_fn)  # 0.25s spacing
    rl.acquire()  # first is free
    rl.acquire()  # must wait ~0.25s
    now[0] += 0.10
    rl.acquire()  # 0.10s elapsed -> wait ~0.15s
    assert slept == [pytest.approx(0.25), pytest.approx(0.15)]


def test_rate_limiter_disabled_when_rps_zero():
    rl = RateLimiter(0.0, sleep_fn=lambda _s: pytest.fail("should not sleep"))
    rl.acquire()
    rl.acquire()
