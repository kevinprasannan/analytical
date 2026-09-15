"""Phase 2.6 — the real INGEST phase (IngestionService) with in-memory repos."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from analytical_core.enums import (
    DataKind,
    InstrumentPhaseOutcome,
    InstrumentType,
    PhaseStatus,
    Timeframe,
)
from app.config import Settings
from app.db.repositories.market_data import MemoryMarketDataRepository
from app.db.repositories.protocols import InstrumentView
from app.ingestion import IngestionService
from app.providers.base import OHLCVBar, ProviderAuthError, ProviderError, ProviderRateLimitError
from app.providers.upstox import UpstoxProvider
from app.providers.upstox.http import UpstoxHTTPClient

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)

FUT = InstrumentView(1, "NIFTY-FUT-2026-09", InstrumentType.FUTURE, True, True, "NSE_FO|68407")
IDX = InstrumentView(2, "NIFTY-INDEX", InstrumentType.INDEX, True, False, "NSE_INDEX|Nifty 50")
OPT = InstrumentView(
    3, "NIFTY-OPT-2026-09-24000-CE", InstrumentType.OPTION, True, True, "NSE_FO|46915"
)


def _m1_rows(n: int, *, start_min=555, oi_base: int | None = 54000):
    rows = []
    for i in range(n):
        t = start_min + i
        row = [f"2026-08-27T{t // 60:02d}:{t % 60:02d}:00+05:30", 100, 101, 99, 100 + i, 10]
        row.append(None if oi_base is None else oi_base + i)
        rows.append(row)
    rows.reverse()
    return rows


def _upstox(handler) -> UpstoxProvider:
    client = UpstoxHTTPClient(
        base_url="https://api.upstox.com",
        token_provider=lambda: "tok",
        transport=httpx.MockTransport(handler),
        max_rps=0,
        sleep_fn=lambda _s: None,
    )
    return UpstoxProvider(
        Settings(active_provider="upstox", upstox_access_token="x"), http_client=client
    )


def _ok_handler(m1_rows, d1_rows):
    def handler(req: httpx.Request) -> httpx.Response:
        candles = d1_rows if "/days/1/" in str(req.url) else m1_rows
        return httpx.Response(200, json={"status": "success", "data": {"candles": candles}})

    return handler


def _service(provider, repo=None):
    return (
        IngestionService(
            provider, repo or MemoryMarketDataRepository(), settings=Settings(), now=NOW
        ),
        repo,
    )


# ======================================================================================
# happy path
# ======================================================================================


def test_ingest_persists_bars_and_marks_instruments_ok():
    repo = MemoryMarketDataRepository()
    provider = _upstox(_ok_handler(_m1_rows(60), [["2026-08-27T00:00:00+05:30", 1, 1, 1, 1, 9, 0]]))
    svc, _ = _service(provider, repo)

    outcome = svc.run([FUT, IDX, OPT])

    assert outcome.status is PhaseStatus.SUCCEEDED
    assert set(outcome.instrument_outcomes.values()) == {InstrumentPhaseOutcome.OK}
    assert outcome.detail["bars_upserted"] > 0
    # M1 + aggregated M5/M15/H1 all present for a derivative
    for tf in (Timeframe.M1, Timeframe.M5, Timeframe.M15, Timeframe.H1, Timeframe.D1):
        assert repo.count_bars(instrument_id=1, timeframe=tf, provider="upstox") > 0
    # per-candle OI only for FUTURE/OPTION
    assert (
        repo.get_watermark(
            instrument_id=1, timeframe=Timeframe.M1, data_kind=DataKind.OI, provider="upstox"
        )
        is not None
    )
    assert (
        repo.get_watermark(
            instrument_id=2, timeframe=Timeframe.M1, data_kind=DataKind.OI, provider="upstox"
        )
        is None
    )


def test_empty_instrument_list_is_a_noop_success():
    svc, _ = _service(_upstox(_ok_handler([], [])))
    outcome = svc.run([])
    assert outcome.status is PhaseStatus.SUCCEEDED
    assert outcome.instrument_outcomes == {}


def test_second_cycle_is_idempotent():
    repo = MemoryMarketDataRepository()
    provider = _upstox(_ok_handler(_m1_rows(60), [["2026-08-27T00:00:00+05:30", 1, 1, 1, 1, 9, 0]]))
    IngestionService(provider, repo, settings=Settings(), now=NOW).run([FUT])
    before = repo.count_bars(instrument_id=1, timeframe=Timeframe.M1, provider="upstox")

    IngestionService(provider, repo, settings=Settings(), now=NOW).run([FUT])
    assert repo.count_bars(instrument_id=1, timeframe=Timeframe.M1, provider="upstox") == before


# ======================================================================================
# resilience
# ======================================================================================


def test_expired_token_skips_every_instrument_and_does_not_crash():
    class Expired:
        provider_id = "upstox"

        def ensure_authenticated(self):
            raise ProviderAuthError("token EXPIRED")

        def fetch_ohlcv(self, *a, **k):  # pragma: no cover - must never be reached
            raise AssertionError("fetch attempted after auth failure")

    repo = MemoryMarketDataRepository()
    outcome = IngestionService(Expired(), repo, settings=Settings(), now=NOW).run([FUT, IDX, OPT])

    assert outcome.status is PhaseStatus.SKIPPED
    assert set(outcome.instrument_outcomes.values()) == {InstrumentPhaseOutcome.SKIPPED}
    assert outcome.detail["reason"] == "provider_auth_failed"
    assert repo.count_bars(instrument_id=1, timeframe=Timeframe.M1, provider="upstox") == 0


def test_per_instrument_provider_error_isolates_to_that_instrument():
    class Flaky:
        provider_id = "upstox"

        def ensure_authenticated(self):
            return None

        def fetch_ohlcv(self, sym, tf, start, end):
            if sym == "NSE_FO|46915":  # the OPTION
                raise ProviderError("boom on 46915")
            if tf is Timeframe.D1:
                return []
            return [
                OHLCVBar(
                    ts=datetime(2026, 8, 27, 3, 45, tzinfo=UTC) + timedelta(minutes=i),
                    open=1,
                    high=1,
                    low=1,
                    close=1,
                    volume=1,
                    is_final=True,
                    source="upstox:v3/historical-candle",
                    open_interest=5000 + i,
                )
                for i in range(10)
            ]

    repo = MemoryMarketDataRepository()
    outcome = IngestionService(Flaky(), repo, settings=Settings(), now=NOW).run([FUT, OPT])

    assert outcome.instrument_outcomes[1] is InstrumentPhaseOutcome.OK
    assert outcome.instrument_outcomes[3] is InstrumentPhaseOutcome.ERROR
    assert outcome.status is PhaseStatus.PARTIAL
    assert repo.count_bars(instrument_id=1, timeframe=Timeframe.M1, provider="upstox") == 10
    assert repo.count_bars(instrument_id=3, timeframe=Timeframe.M1, provider="upstox") == 0


def test_throttled_instrument_is_degraded_and_watermark_marked():
    class Throttled:
        provider_id = "upstox"

        def ensure_authenticated(self):
            return None

        def fetch_ohlcv(self, *a, **k):
            raise ProviderRateLimitError("429")

    repo = MemoryMarketDataRepository()
    outcome = IngestionService(Throttled(), repo, settings=Settings(), now=NOW).run([FUT])

    assert outcome.instrument_outcomes[1] is InstrumentPhaseOutcome.DEGRADED
    assert outcome.status is PhaseStatus.PARTIAL
    wm = repo.get_watermark(
        instrument_id=1, timeframe=Timeframe.M1, data_kind=DataKind.OHLCV, provider="upstox"
    )
    assert wm.last_status.value == "RATE_LIMITED"
    assert wm.last_complete_ts is None  # nothing pulled


def test_token_expiring_mid_cycle_skips_only_the_affected_instrument():
    class MidExpiry:
        provider_id = "upstox"

        def ensure_authenticated(self):
            return None  # still valid at phase start

        def fetch_ohlcv(self, sym, tf, start, end):
            if sym == "NSE_INDEX|Nifty 50":
                raise ProviderAuthError("token EXPIRED mid-cycle")
            if tf is Timeframe.D1:
                return []
            return [
                OHLCVBar(
                    ts=datetime(2026, 8, 27, 3, 45, tzinfo=UTC),
                    open=1,
                    high=1,
                    low=1,
                    close=1,
                    volume=1,
                    is_final=True,
                    source="upstox:v3/historical-candle",
                    open_interest=1,
                )
            ]

    outcome = IngestionService(
        MidExpiry(), MemoryMarketDataRepository(), settings=Settings(), now=NOW
    ).run([FUT, IDX])
    assert outcome.instrument_outcomes[1] is InstrumentPhaseOutcome.OK
    assert outcome.instrument_outcomes[2] is InstrumentPhaseOutcome.SKIPPED
    assert outcome.status is PhaseStatus.PARTIAL
