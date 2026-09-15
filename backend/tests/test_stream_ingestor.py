"""End-to-end streaming ingestor on the synthetic feed (docs/02 §3.4, Phase S2).

`StubMarketFeed` ticks -> `M1Accumulator` -> `MemoryMarketDataRepository`. The
deterministic cycle is untouched; this only exercises the forming-M1 + live-OI
path.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from analytical_core.enums import Timeframe
from app.db.repositories.market_data import MemoryMarketDataRepository
from app.ingestion.stream import StreamIngestor
from app.providers.stub.feed import StubMarketFeed

T0 = datetime(2026, 8, 31, 3, 45, tzinfo=UTC)  # 09:15 IST


def _run(feed, repo, symbol_map, *, mode="full", now_fn=lambda: T0):
    ing = StreamIngestor(
        feed,
        repo,
        symbol_to_instrument=symbol_map,
        provider="stub",
        grace_seconds=90,
        flush_interval_seconds=10,
        now_fn=now_fn,
    )
    ing.run(list(symbol_map), mode=mode)
    return ing


def _m1_bars(repo, instrument_id):
    return repo.load_bars(
        instrument_id=instrument_id, timeframe=Timeframe.M1, provider="stub", limit=100
    )


def test_stub_feed_produces_three_m1_bars_with_oi():
    repo = MemoryMarketDataRepository()
    feed = StubMarketFeed(start=T0, minutes=3, interval_seconds=5)
    ing = _run(feed, repo, {"NIFTY": 1})

    bars = _m1_bars(repo, 1)
    assert [b.ts for b in bars] == [T0, T0 + timedelta(minutes=1), T0 + timedelta(minutes=2)]
    for b in bars:
        assert b.high >= b.low
        assert b.open > 0
    assert ing.ticks_seen == 36  # (3 * 60) / 5
    # OI travelled through on `mode="full"`
    oi = repo.load_oi(instrument_id=1, timeframe=Timeframe.M1, provider="stub", limit=100)
    assert len(oi) == 3
    assert all(r.oi > 0 for r in oi)


def test_final_flush_marks_only_the_trailing_bar_final():
    repo = MemoryMarketDataRepository()
    feed = StubMarketFeed(start=T0, minutes=3, interval_seconds=5)
    _run(feed, repo, {"NIFTY": 1})

    bars = _m1_bars(repo, 1)
    # rolled bars are still inside their 90s grace when they roll -> not final;
    # the run-end flush(now + 1 day) finalises whatever is still forming.
    assert [b.is_final for b in bars] == [False, False, True]


def test_ltpc_mode_carries_no_open_interest():
    repo = MemoryMarketDataRepository()
    feed = StubMarketFeed(start=T0, minutes=2, interval_seconds=5)
    _run(feed, repo, {"NIFTY": 1}, mode="ltpc")

    assert _m1_bars(repo, 1)  # bars still produced
    assert repo.load_oi(instrument_id=1, timeframe=Timeframe.M1, provider="stub", limit=100) == []


def test_unmapped_symbols_are_skipped():
    repo = MemoryMarketDataRepository()
    feed = StubMarketFeed(start=T0, minutes=2, interval_seconds=5)
    ing = _run(feed, repo, {"NIFTY": 1})  # feed also streams BANKNIFTY below

    # re-run with an extra unmapped symbol on a fresh feed/ingestor
    repo2 = MemoryMarketDataRepository()
    feed2 = StubMarketFeed(start=T0, minutes=2, interval_seconds=5)
    ing2 = StreamIngestor(
        feed2, repo2, symbol_to_instrument={"NIFTY": 1}, provider="stub", now_fn=lambda: T0
    )
    ing2.run(["NIFTY", "BANKNIFTY"], mode="full")

    assert _m1_bars(repo2, 1)
    assert (
        repo2.load_bars(instrument_id=2, timeframe=Timeframe.M1, provider="stub", limit=100) == []
    )
    assert ing2.ticks_seen == ing.ticks_seen * 2  # both symbols seen, one persisted


def test_serve_exits_immediately_when_stop_event_is_preset():
    import threading

    from app.config import Settings
    from app.ingestion.stream import serve

    stop = threading.Event()
    stop.set()
    rc = serve(
        Settings(active_provider="stub", scheduler_session_only=False),
        stop_event=stop,
        install_signals=False,  # not the main thread contract
    )
    assert rc == 0


def test_periodic_flush_writes_a_forming_bar_mid_stream():
    repo = MemoryMarketDataRepository()
    feed = StubMarketFeed(start=T0, minutes=3, interval_seconds=5)
    clock = [T0]

    def now_fn():
        clock[0] += timedelta(seconds=30)  # advance past flush_interval every tick
        return clock[0]

    ing = StreamIngestor(
        feed,
        repo,
        symbol_to_instrument={"NIFTY": 1},
        provider="stub",
        flush_interval_seconds=10,
        now_fn=now_fn,
    )
    ing.run(["NIFTY"], mode="full")

    # end state is still the three finalised/rolled minutes (forming writes were
    # upserted in place on the same bar-open key)
    bars = _m1_bars(repo, 1)
    assert [b.ts for b in bars] == [T0, T0 + timedelta(minutes=1), T0 + timedelta(minutes=2)]
