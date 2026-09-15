"""Phase 2.5 — historical backfill orchestration (no DB; MemoryMarketDataRepository).

Provider I/O is driven through the real ``UpstoxProvider`` over ``httpx.MockTransport``
so pagination + the shared budget are exercised; a tiny fake provider covers the
error branches.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from analytical_core.enums import DataKind, InstrumentType, Timeframe
from app.config import Settings
from app.db.repositories.market_data import MemoryMarketDataRepository
from app.ingestion.backfill import BackfillService, BackfillTarget
from app.ingestion.budget import RequestBudget
from app.providers.base import OHLCVBar, ProviderAuthError, ProviderRateLimitError
from app.providers.upstox import UpstoxProvider
from app.providers.upstox.http import UpstoxHTTPClient

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)  # well after the 2026-08-27 session close
FUT = BackfillTarget(1, "NSE_FO|68407", InstrumentType.FUTURE, "NIFTY-FUT-2026-09")
IDX = BackfillTarget(2, "NSE_INDEX|Nifty 50", InstrumentType.INDEX, "NIFTY-INDEX")


def _m1_rows(n: int, *, day="2026-08-27", oi_base: int | None = 54000, start_min=555):
    # start_min defaults to 09:15 IST (9*60 + 15) minutes past midnight
    rows = []
    for i in range(n):
        t = start_min + i
        row = [f"{day}T{t // 60:02d}:{t % 60:02d}:00+05:30", 100 + i, 101 + i, 99 + i, 100 + i, 10]
        row.append(None if oi_base is None else oi_base + i)
        rows.append(row)
    rows.reverse()  # Upstox returns newest-first
    return rows


def _d1_rows(days: list[str]):
    return [[f"{d}T00:00:00+05:30", 100, 105, 95, 102, 5000, 0] for d in reversed(days)]


def _handler(*, m1_rows, d1_rows, on_request=None):
    def handler(req: httpx.Request) -> httpx.Response:
        if on_request:
            r = on_request(req)
            if r is not None:
                return r
        if "/days/1/" in str(req.url):
            return httpx.Response(200, json={"status": "success", "data": {"candles": d1_rows}})
        return httpx.Response(200, json={"status": "success", "data": {"candles": m1_rows}})

    return handler


def _service(handler, repo=None, *, budget=None, now=NOW, settings=None):
    budget = budget or RequestBudget(max_rps=0, per_30min=0)
    client = UpstoxHTTPClient(
        base_url="https://api.upstox.com",
        token_provider=lambda: "tok",
        transport=httpx.MockTransport(handler),
        limiter=budget,
    )
    provider = UpstoxProvider(
        Settings(active_provider="upstox", upstox_access_token="x"), http_client=client
    )
    repo = repo or MemoryMarketDataRepository()
    svc = BackfillService(
        provider=provider,
        repo=repo,
        budget=budget,
        settings=settings or Settings(),
        now_fn=lambda: now,
    )
    return svc, repo


# ======================================================================================
# happy path: persist all timeframes + OI, aggregate, advance watermarks
# ======================================================================================


def test_full_backfill_persists_native_and_aggregated_bars_and_oi():
    handler = _handler(
        m1_rows=_m1_rows(60), d1_rows=_d1_rows(["2026-08-25", "2026-08-26", "2026-08-27"])
    )
    svc, repo = _service(handler)
    report = svc.run([FUT])

    r = report.instruments[0]
    assert r.status.value == "OK"
    assert r.bars["D1"].inserted == 3
    assert r.bars["M1"].inserted == 60
    assert r.bars["M5"].inserted == 12  # 60 M1 -> 12 M5
    assert r.bars["M15"].inserted == 4
    assert r.bars["H1"].inserted == 1  # all within the first hour
    assert r.oi.inserted == 60

    assert repo.count_bars(instrument_id=1, timeframe=Timeframe.M1, provider="upstox") == 60
    wm = repo.get_watermark(
        instrument_id=1, timeframe=Timeframe.M1, data_kind=DataKind.OHLCV, provider="upstox"
    )
    assert wm.last_complete_ts == datetime(2026, 8, 27, 4, 44, tzinfo=UTC)  # 10:14 IST, last final
    assert wm.last_status.value == "OK"
    oi_wm = repo.get_watermark(
        instrument_id=1, timeframe=Timeframe.M1, data_kind=DataKind.OI, provider="upstox"
    )
    assert oi_wm.last_complete_ts == wm.last_complete_ts


def test_index_backfill_writes_no_open_interest_rows():
    handler = _handler(m1_rows=_m1_rows(30, oi_base=None), d1_rows=_d1_rows(["2026-08-27"]))
    svc, repo = _service(handler)
    r = svc.run([IDX]).instruments[0]
    assert r.oi.total == 0
    assert (
        repo.get_watermark(
            instrument_id=2, timeframe=Timeframe.M1, data_kind=DataKind.OI, provider="upstox"
        )
        is None
    )


# ======================================================================================
# resume-safe / idempotent
# ======================================================================================


def test_second_run_is_idempotent_and_resumes_from_watermark():
    handler = _handler(m1_rows=_m1_rows(60), d1_rows=_d1_rows(["2026-08-27"]))
    svc, repo = _service(handler)
    svc.run([FUT])
    before = repo.count_bars(instrument_id=1, timeframe=Timeframe.M1, provider="upstox")

    r2 = svc.run([FUT]).instruments[0]
    assert r2.bars["M1"].inserted == 0 and r2.bars["M1"].updated == 60  # re-verified, no dupes
    assert r2.bars["M5"].inserted == 0
    assert repo.count_bars(instrument_id=1, timeframe=Timeframe.M1, provider="upstox") == before


def test_watermark_never_advances_past_a_non_final_bar():
    # a fake provider whose newest 5 M1 bars are still forming (is_final=False)
    class P:
        provider_id = "upstox"

        def fetch_ohlcv(self, sym, tf, start, end):
            if tf is Timeframe.D1:
                return []
            out = []
            for i in range(30):  # 09:15..09:44 IST
                out.append(
                    OHLCVBar(
                        ts=datetime(2026, 8, 27, 3, 45, tzinfo=UTC) + timedelta(minutes=i),
                        open=1,
                        high=1,
                        low=1,
                        close=1,
                        volume=1,
                        is_final=(i < 25),
                        source="upstox:v3/historical-candle",
                        open_interest=5000 + i,
                    )
                )
            return out

    svc, repo = _service_with_provider(P())
    svc.run([FUT])
    wm = repo.get_watermark(
        instrument_id=1, timeframe=Timeframe.M1, data_kind=DataKind.OHLCV, provider="upstox"
    )
    assert wm.last_complete_ts == datetime(2026, 8, 27, 4, 9, tzinfo=UTC)  # 09:39 IST = 25th bar
    # but every fetched bar (final or not) is still persisted
    assert repo.count_bars(instrument_id=1, timeframe=Timeframe.M1, provider="upstox") == 30


# ======================================================================================
# error handling / progress tracking
# ======================================================================================


class _FakeProvider:
    provider_id = "upstox"

    def __init__(self, exc):
        self._exc = exc

    def fetch_ohlcv(self, *_a, **_k):
        raise self._exc


def _service_with_provider(provider, now=NOW):
    repo = MemoryMarketDataRepository()
    svc = BackfillService(
        provider=provider,
        repo=repo,
        budget=RequestBudget(max_rps=0, per_30min=0),
        settings=Settings(),
        now_fn=lambda: now,
    )
    return svc, repo


def test_rate_limit_is_recorded_and_does_not_crash():
    svc, repo = _service_with_provider(_FakeProvider(ProviderRateLimitError("429")))
    r = svc.run([FUT]).instruments[0]
    assert r.status.value == "RATE_LIMITED"
    assert r.error and "429" in r.error
    wm = repo.get_watermark(
        instrument_id=1, timeframe=Timeframe.M1, data_kind=DataKind.OHLCV, provider="upstox"
    )
    assert wm.last_complete_ts is None  # nothing pulled -> watermark not advanced
    assert wm.last_status.value == "RATE_LIMITED"


def test_auth_failure_is_recorded():
    svc, repo = _service_with_provider(_FakeProvider(ProviderAuthError("expired")))
    r = svc.run([FUT]).instruments[0]
    assert r.status.value == "AUTH_FAILED"


def test_partial_progress_persists_before_a_later_failure():
    # D1 succeeds, M1 raises
    class P:
        provider_id = "upstox"

        def fetch_ohlcv(self, sym, tf, start, end):
            if tf is Timeframe.D1:
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
                    )
                ]
            raise ProviderRateLimitError("429 on M1")

    svc, repo = _service_with_provider(P())
    r = svc.run([FUT]).instruments[0]
    assert r.bars["D1"].inserted == 1  # D1 saved
    assert "M1" not in r.bars  # M1 never fetched
    assert r.status.value == "RATE_LIMITED"
    d1_wm = repo.get_watermark(
        instrument_id=1, timeframe=Timeframe.D1, data_kind=DataKind.OHLCV, provider="upstox"
    )
    assert d1_wm.last_complete_ts == datetime(2026, 8, 27, 3, 45, tzinfo=UTC)


# ======================================================================================
# no fabrication / gap metric
# ======================================================================================


def test_no_bar_is_fabricated_for_a_sparse_fetch():
    # provider returns minutes 15,16, then 20,21 (a 3-minute interior gap)
    rows = [
        ["2026-08-27T09:21:00+05:30", 100, 101, 99, 100, 10, 5],
        ["2026-08-27T09:20:00+05:30", 100, 101, 99, 100, 10, 4],
        ["2026-08-27T09:16:00+05:30", 100, 101, 99, 100, 10, 2],
        ["2026-08-27T09:15:00+05:30", 100, 101, 99, 100, 10, 1],
    ]
    svc, repo = _service(_handler(m1_rows=rows, d1_rows=_d1_rows(["2026-08-27"])))
    r = svc.run([FUT]).instruments[0]
    assert r.bars["M1"].inserted == 4  # exactly what the provider sent
    assert r.m1_gap_count == 3  # 09:17, 09:18, 09:19 reported, not filled
    assert repo.count_bars(instrument_id=1, timeframe=Timeframe.M1, provider="upstox") == 4


# ======================================================================================
# concurrency
# ======================================================================================


def test_concurrent_and_serial_backfill_agree():
    handler = _handler(m1_rows=_m1_rows(30), d1_rows=_d1_rows(["2026-08-27"]))
    t1 = FUT
    t2 = BackfillTarget(3, "NSE_FO|70105", InstrumentType.OPTION, "BANKNIFTY-OPT-2026-09-54000-CE")

    svc_a, repo_a = _service(handler)
    rep_serial = svc_a.run([t1, t2], concurrency=1)

    svc_b, repo_b = _service(handler)
    rep_conc = svc_b.run([t1, t2], concurrency=4)

    def digest(repo):
        return sorted(
            (iid, tf.value, ts.isoformat(), str(b.close))
            for (iid, tf, _p, ts), b in repo._bars.items()
        )

    assert digest(repo_a) == digest(repo_b)
    assert [i.bars["M1"].total for i in rep_serial.instruments] == [
        i.bars["M1"].total for i in rep_conc.instruments
    ]
    assert rep_conc.budget["granted"] == rep_serial.budget["granted"]


# ======================================================================================
# repair-only
# ======================================================================================


def test_repair_only_reverifies_and_updates_without_extending_history():
    handler = _handler(m1_rows=_m1_rows(30, oi_base=54000), d1_rows=_d1_rows(["2026-08-27"]))
    svc, repo = _service(handler)
    svc.run([FUT])

    # provider restates the same bars with a different close
    restated = _m1_rows(30, oi_base=54000)
    for row in restated:
        row[4] = 999  # close
    svc2, _ = _service(_handler(m1_rows=restated, d1_rows=_d1_rows(["2026-08-27"])), repo=repo)
    r = svc2.run([FUT], repair_only=True).instruments[0]
    assert r.bars["M1"].updated >= 1 and r.bars["M1"].inserted == 0
    some = next(
        b for (iid, tf, _p, _ts), b in repo._bars.items() if iid == 1 and tf is Timeframe.M1
    )
    assert str(some.close) == "999"
