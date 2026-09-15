"""Golden-cross grid (docs/07 §4.19) — the pure piece: reading the fast/slow
MAs as dynamic support/resistance. The DB endpoint is exercised by
``test_api_*_db`` under ``@pytest.mark.db``."""

from __future__ import annotations

from app.api.services import _gc_ma_proximity


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
