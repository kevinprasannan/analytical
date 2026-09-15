"""Multi-timeframe candle grid (docs/07 §4.17) — the pure pieces: the on-read
M5→M30 session fold and one column's shape. The DB endpoint is exercised by
``test_api_*_db`` under ``@pytest.mark.db``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.api.services import _candles_grid_column, _fold_m5_to_m30, _GBar

# 2026-01-05 is a Monday; NSE session opens 09:15 IST = 03:45 UTC.
_OPEN = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)


def _m5(n: int, *, start_px: float = 100.0, step: float = 1.0) -> list[_GBar]:
    out = []
    px = start_px
    for i in range(n):
        o, c = px, px + step
        out.append(
            _GBar(
                ts=_OPEN + timedelta(minutes=5 * i),
                open=o,
                high=max(o, c) + 0.5,
                low=min(o, c) - 0.5,
                close=c,
                volume=100 + i,
                is_final=True,
            )
        )
        px = c
    return out


def test_fold_m5_to_m30_is_session_anchored_and_ohlc_correct():
    m5 = _m5(6)  # exactly one 30-min slot (09:15–09:45)
    m30 = _fold_m5_to_m30(m5)
    assert len(m30) == 1
    b = m30[0]
    assert b.ts == _OPEN  # anchored to session open, not first child
    assert b.open == m5[0].open
    assert b.close == m5[-1].close
    assert b.high == max(k.high for k in m5)
    assert b.low == min(k.low for k in m5)
    assert b.volume == sum(k.volume for k in m5)


def test_fold_m5_to_m30_buckets_and_drops_pre_open():
    pre = [
        _GBar(_OPEN - timedelta(minutes=5), 99, 99.5, 98.5, 99, 10, True),
        _GBar(_OPEN - timedelta(minutes=10), 98, 98.5, 97.5, 98, 10, True),
    ]
    m30 = _fold_m5_to_m30(pre + _m5(13))  # 13 M5 → slots [0..5], [6..11], [12]
    assert [b.ts for b in m30] == [
        _OPEN,
        _OPEN + timedelta(minutes=30),
        _OPEN + timedelta(minutes=60),
    ]


def test_fold_empty_is_empty():
    assert _fold_m5_to_m30([]) == []


def test_column_insufficient_when_too_few_bars():
    col = _candles_grid_column("M30", _m5(4), limit=5)
    assert col["timeframe"] == "M30"
    assert col["status"] == "INSUFFICIENT_DATA"
    assert col["patterns"] == []


def test_column_ok_reports_patterns_capped_at_limit():
    # a long clean downtrend then a hammer-shaped last bar
    bars = []
    px = 200.0
    for i in range(30):
        o, c = px, px - 2.0
        bars.append(_GBar(_OPEN + timedelta(minutes=15 * i), o, o + 0.4, c - 0.4, c, 100, True))
        px = c
    p = bars[-1].close
    bars.append(_GBar(_OPEN + timedelta(minutes=15 * 30), p - 1.5, p + 0.3, p - 6.0, p, 100, True))
    col = _candles_grid_column("M15", bars, limit=2)
    assert col["status"] == "OK"
    assert len(col["patterns"]) <= 2
    assert col["bars_scanned"] >= 1
    # descriptive only
    blob = repr(col).upper()
    for banned in ("BUY", "SELL", "ENTRY", "TARGET", "STOP LOSS"):
        assert banned not in blob
