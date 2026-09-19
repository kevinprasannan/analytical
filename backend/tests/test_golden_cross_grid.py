"""Golden-cross grid (docs/07 §4.19) — the pure piece: reading the fast/slow
MAs as dynamic support/resistance. The DB endpoint is exercised by
``test_api_*_db`` under ``@pytest.mark.db``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from analytical_core.enums import InstrumentType
from app.api.services import _GBar, _gc_grid_column, _gc_ma_proximity


def test_near_slow_ma_from_above_reads_support():
    out = _gc_ma_proximity(100.1, fast=95.0, slow=100.0, near_pct=0.003)
    assert out["near_slow"] is True
    assert out["near_fast"] is False
    assert out["nearest_ma"] == "SLOW"
    assert out["nearest_ma_side"] == "SUPPORT"
    assert out["dist_to_slow_pct"] == 0.001


def test_near_fast_ma_from_below_reads_resistance():
    out = _gc_ma_proximity(94.9, fast=95.0, slow=80.0, near_pct=0.003)
    assert out["near_fast"] is True
    assert out["near_slow"] is False
    assert out["nearest_ma"] == "FAST"
    assert out["nearest_ma_side"] == "RESISTANCE"


def test_far_from_both_mas_is_not_near():
    out = _gc_ma_proximity(150.0, fast=95.0, slow=80.0, near_pct=0.003)
    assert out["near_fast"] is False
    assert out["near_slow"] is False
    assert out["nearest_ma"] is None
    assert out["nearest_ma_side"] is None


def test_nearer_ma_wins_when_both_are_near():
    # slow at 100.05 (0.05% away) is nearer than fast at 100.2 (0.2% away);
    # both are within the default 0.3% band
    out = _gc_ma_proximity(100.0, fast=100.2, slow=100.05, near_pct=0.003)
    assert out["near_fast"] is True
    assert out["near_slow"] is True
    assert out["nearest_ma"] == "SLOW"


def test_missing_ma_is_skipped_not_an_error():
    out = _gc_ma_proximity(100.0, fast=None, slow=100.05, near_pct=0.003)
    assert out["dist_to_fast_pct"] is None
    assert out["near_fast"] is False
    assert out["nearest_ma"] == "SLOW"


def _bars(n: int, start: float = 100.0, step: float = 0.5) -> list[_GBar]:
    import math

    base = datetime(2026, 1, 1, tzinfo=UTC)
    # a rising series with a wobble — a straight-line ramp makes EMA and SMA
    # converge to the exact same steady-state lag, which would defeat the
    # "these are two different computations" check below
    closes = [start + i * step + 5 * math.sin(i / 7) for i in range(n)]
    return [
        _GBar(
            ts=base + timedelta(minutes=i),
            open=closes[i],
            high=closes[i] + 1,
            low=closes[i] - 1,
            close=closes[i],
            volume=1000,
            is_final=True,
        )
        for i in range(n)
    ]


def test_ema_fast_slow_reported_alongside_the_dma_cross():
    from analytical_core.indicators._common import ema_series

    # >= slow_period (default 200) + cross_search_window bars so the primary
    # SMA-based read is OK, not just the supplementary EMA one
    bars = _bars(260)
    col = _gc_grid_column("D1", bars, InstrumentType.INDEX, near_pct=0.003)
    assert col["status"] == "OK"
    assert col["fast"] is not None and col["slow"] is not None  # DMA (SMA) unaffected
    assert col["ema_fast"] is not None
    assert col["ema_slow"] is not None
    assert col["ema_fast"] != col["fast"] or col["ema_slow"] != col["slow"]
    closes = [b.close for b in bars]
    assert col["ema_fast"] == round(ema_series(closes, 50)[-1], 4)
    assert col["ema_slow"] == round(ema_series(closes, 200)[-1], 4)


def test_ema_fields_absent_on_insufficient_data():
    col = _gc_grid_column("D1", _bars(5), InstrumentType.INDEX, near_pct=0.003)
    assert col["status"] == "INSUFFICIENT_DATA"
    assert col["ema_fast"] is None
    assert col["ema_slow"] is None
