"""Items 6 & 8 — provider interface compliance and capability branching."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from analytical_core.enums import AnalysisScope, Timeframe
from app.providers.base import (
    AuthProvider,
    CapabilityReportingProvider,
    HistoricalMarketDataProvider,
    InstrumentMasterProvider,
    MarketDataProvider,
    OpenInterestProvider,
)
from app.providers.capabilities import (
    OIMode,
    ProviderCapabilities,
    resolve_oi_plan,
    resolve_timeframe_plan,
)
from app.providers.stub import StubProvider

_ALL_PROTOCOLS = [
    AuthProvider,
    InstrumentMasterProvider,
    HistoricalMarketDataProvider,
    OpenInterestProvider,
    CapabilityReportingProvider,
    MarketDataProvider,
]


@pytest.mark.parametrize("proto", _ALL_PROTOCOLS)
def test_stub_provider_satisfies_every_protocol(stub_provider, proto):
    assert isinstance(stub_provider, proto)


@pytest.mark.parametrize("proto", _ALL_PROTOCOLS)
def test_upstox_provider_satisfies_every_protocol(tmp_path, proto):
    from app.config import Settings
    from app.providers.upstox import UpstoxProvider

    provider = UpstoxProvider(
        Settings(active_provider="upstox", upstox_token_file=str(tmp_path / "t.json"))
    )
    assert isinstance(provider, proto)


def test_upstox_capabilities_trace_to_validation_evidence():
    from app.config import Settings
    from app.providers.upstox import UpstoxProvider

    caps = UpstoxProvider(Settings(upstox_token_file="/nonexistent")).capabilities()
    assert caps.provider == "upstox"
    assert caps.oi_mode is OIMode.PER_TIMEFRAME  # PV-4 branch A
    assert {tf.value for tf in caps.native_timeframes} == {"M1", "D1"}  # PV-2
    assert caps.needs_aggregation(Timeframe.H1) and caps.needs_aggregation(Timeframe.M5)
    assert not caps.needs_aggregation(Timeframe.D1)
    assert (caps.rate_limit_per_sec, caps.requests_per_minute, caps.requests_per_30min) == (
        50,
        500,
        2000,
    )  # PV-5
    assert "docs/11" in caps.notes


def test_stub_capabilities_are_explicit_and_labelled_synthetic():
    caps = StubProvider().capabilities()
    assert isinstance(caps, ProviderCapabilities)
    assert "SYNTHETIC" in caps.notes.upper() and "NOT UPSTOX" in caps.notes.upper()


def test_capability_branching_oi_plan_follows_provider_not_a_hardcode():
    snap = ProviderCapabilities(
        "x", "static-token", True, frozenset({Timeframe.M5}), None, OIMode.SNAPSHOT
    )
    per_tf = ProviderCapabilities(
        "y", "static-token", True, frozenset({Timeframe.M5}), None, OIMode.PER_TIMEFRAME
    )
    none = ProviderCapabilities(
        "z", "static-token", True, frozenset({Timeframe.M5}), None, OIMode.NONE
    )
    assert resolve_oi_plan(snap).scope is AnalysisScope.SNAPSHOT
    assert resolve_oi_plan(per_tf).scope is AnalysisScope.PER_TIMEFRAME
    assert resolve_oi_plan(none).available is False


def test_capability_branching_timeframe_plan_native_vs_aggregate_vs_unavailable():
    caps = ProviderCapabilities(
        "x",
        "static-token",
        True,
        native_timeframes=frozenset({Timeframe.M1, Timeframe.D1}),
        aggregatable_from=Timeframe.M1,
        oi_mode=OIMode.NONE,
    )
    plan = resolve_timeframe_plan(caps, (Timeframe.M5, Timeframe.D1, Timeframe.H1))
    assert plan[Timeframe.D1].mode == "native"
    assert plan[Timeframe.M5].mode == "aggregate"
    assert plan[Timeframe.M5].aggregate_from is Timeframe.M1
    assert plan[Timeframe.H1].mode == "aggregate"  # can also come from M1

    no_agg = ProviderCapabilities(
        "y", "static-token", True, frozenset({Timeframe.D1}), None, OIMode.NONE
    )
    plan2 = resolve_timeframe_plan(no_agg, (Timeframe.M5,))
    assert plan2[Timeframe.M5].mode == "unavailable"


def test_historical_call_shape(stub_provider):
    end = datetime.now(tz=UTC)
    bars = stub_provider.fetch_ohlcv(
        "STUB:NIFTY-INDEX", Timeframe.M5, end - timedelta(hours=1), end
    )
    assert bars and all(b.source == "STUB_FIXTURE" for b in bars)
    assert all(b.ts.tzinfo is not None for b in bars)  # tz-aware (bar-open UTC)


def test_upstox_historical_call_shape_over_mock_transport():
    """The real adapter honours the same contract as the stub — tz-aware bars, a
    non-synthetic ``source`` — with zero live calls (injected transport)."""
    import httpx

    from app.config import Settings
    from app.providers.upstox import UpstoxProvider
    from app.providers.upstox.http import UpstoxHTTPClient

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"].startswith("Bearer ")
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "candles": [
                        ["2026-08-27T09:16:00+05:30", 100.5, 101, 100, 100.75, 1200, 55000],
                        ["2026-08-27T09:15:00+05:30", 100, 100.6, 99.9, 100.5, 1000, 54000],
                    ]
                },
            },
        )

    client = UpstoxHTTPClient(
        base_url="https://api.upstox.com",
        token_provider=lambda: "tok",
        transport=httpx.MockTransport(handler),
        max_rps=0,
    )
    provider = UpstoxProvider(
        Settings(active_provider="upstox", upstox_access_token="envtok"), http_client=client
    )
    end = datetime(2026, 8, 27, 23, 59, tzinfo=UTC)
    bars = provider.fetch_ohlcv("NSE_FO|68407", Timeframe.M1, end - timedelta(hours=2), end)

    assert [b.ts for b in bars] == sorted(b.ts for b in bars)  # ascending
    assert all(b.ts.tzinfo is not None for b in bars)
    assert all(b.source == "upstox:v3/historical-candle" for b in bars)
    assert all(b.source != "STUB_FIXTURE" for b in bars)
    assert [b.open_interest for b in bars] == [54000, 55000]
