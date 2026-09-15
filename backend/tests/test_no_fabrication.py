"""Item 18 — no fabricated bars / data are introduced (docs/09 §2.5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from analytical_core.enums import RunPhase, Timeframe
from app.db.repositories.memory import build_memory_repositories
from app.providers.stub import StubBehavior, StubProvider
from app.providers.stub.fixtures import stub_ohlcv
from app.worker.cycle import run_cycle

BACKEND = Path(__file__).resolve().parents[1]


def test_empty_provider_response_yields_no_bars_and_no_placeholder():
    p = StubProvider(StubBehavior(empty_symbols=frozenset({"S"})))
    end = datetime.now(tz=UTC)
    assert p.fetch_ohlcv("S", Timeframe.M5, end - timedelta(hours=1), end) == []


def test_ingest_records_zero_bars_without_inventing_any(sample_instruments):
    repos, store = build_memory_repositories(sample_instruments)
    behavior = StubBehavior(empty_symbols=frozenset(i.provider_symbol for i in sample_instruments))
    result = run_cycle(repos, StubProvider(behavior))
    ingest = store.phase_status[(result.run_id, RunPhase.INGEST)]
    # every instrument OK with bars == 0 (a valid no-data result, not an error)
    assert all(v == 0 for v in ingest["detail"]["bars"].values())
    assert result.crashed is False


def test_stub_series_is_formula_based_not_random():
    w = (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC))
    a = stub_ohlcv("X", Timeframe.M5, *w)
    b = stub_ohlcv("X", Timeframe.M5, *w)
    assert [x.close for x in a] == [x.close for x in b]


def test_no_module_carries_forward_or_synthesises_ohlc():
    """Static guard: production code must not 'carry forward' / 'fill' missing bars."""
    banned = ("carry forward", "carry_forward", "forward fill", "ffill", "synthesize ohlc")
    for path in (BACKEND / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for phrase in banned:
            assert phrase not in text, f"{path} mentions {phrase!r}"
