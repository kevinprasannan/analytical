"""Item 7 — stub-provider deterministic behaviour and its failure modes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from analytical_core.enums import ProviderAuthState, Timeframe
from app.providers.base import (
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderUnavailableCapabilityError,
)
from app.providers.stub import StubBehavior, StubProvider
from app.providers.stub.fixtures import FIXTURE_DISCLAIMER, STUB_INSTRUMENTS

_WINDOW = (datetime.now(tz=UTC) - timedelta(hours=2), datetime.now(tz=UTC))


def test_output_is_deterministic():
    a = StubProvider().fetch_ohlcv("STUB:NIFTY-INDEX", Timeframe.M5, *_WINDOW)
    b = StubProvider().fetch_ohlcv("STUB:NIFTY-INDEX", Timeframe.M5, *_WINDOW)
    assert [(x.open, x.high, x.low, x.close, x.volume) for x in a] == [
        (x.open, x.high, x.low, x.close, x.volume) for x in b
    ]


def test_fixtures_are_marked_not_real():
    assert "NOT REAL MARKET DATA" in FIXTURE_DISCLAIMER
    assert all(r.source == "STUB_FIXTURE" for r in STUB_INSTRUMENTS)
    for bar in StubProvider().fetch_ohlcv("STUB:NIFTY-INDEX", Timeframe.M5, *_WINDOW):
        assert bar.source == "STUB_FIXTURE"


def test_success_path_instrument_master():
    recs = StubProvider().fetch_instrument_master()
    assert {r.instrument_type.value for r in recs} >= {"INDEX", "FUTURE", "OPTION"}


def test_no_data_returns_empty_never_fabricates():
    p = StubProvider(StubBehavior(empty_symbols=frozenset({"STUB:NIFTY-INDEX"})))
    assert p.fetch_ohlcv("STUB:NIFTY-INDEX", Timeframe.M5, *_WINDOW) == []
    assert p.fetch_oi_series("STUB:NIFTY-INDEX", Timeframe.M5, *_WINDOW) == []


def test_authentication_failure():
    p = StubProvider(StubBehavior(auth_state=ProviderAuthState.EXPIRED))
    assert p.auth_state() is ProviderAuthState.EXPIRED
    with pytest.raises(ProviderAuthError):
        p.ensure_authenticated()
    with pytest.raises(ProviderAuthError):
        p.fetch_instrument_master()


def test_rate_limit_and_transient_error():
    rl = StubProvider(StubBehavior(rate_limited_symbols=frozenset({"S"})))
    with pytest.raises(ProviderRateLimitError):
        rl.fetch_ohlcv("S", Timeframe.M5, *_WINDOW)
    err = StubProvider(StubBehavior(error_symbols=frozenset({"S"})))
    with pytest.raises(ProviderError):
        err.fetch_ohlcv("S", Timeframe.M5, *_WINDOW)


def test_unavailable_capability():
    p = StubProvider(StubBehavior(unavailable_capabilities=frozenset({"oi_series"})))
    with pytest.raises(ProviderUnavailableCapabilityError):
        p.fetch_oi_series("S", Timeframe.M5, *_WINDOW)
    # snapshot still works
    assert p.fetch_oi_snapshot(["STUB:NIFTY-FUT-NEAR"])
