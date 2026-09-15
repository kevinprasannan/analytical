"""ICT swing Fair Value Gaps (docs/05 §9c) — pure detection + state."""

from __future__ import annotations

from analytical_core.fvg import FvgState, scan_swing_fvgs


def _bars(seq):
    h = tuple(float(x[0]) for x in seq)
    low = tuple(float(x[1]) for x in seq)
    c = tuple(float(x[2]) for x in seq)
    return h, low, c


P = {"swing_lookback": 2, "pre_swing_window": 6}


def test_insufficient_data_is_empty():
    h, low, c = _bars([(10, 9, 9.5)] * 6)
    s = scan_swing_fvgs(h, low, c)
    assert s.fvgs == [] and s.bias == "NEUTRAL"


def test_bullish_fvg_into_a_swing_high_is_a_bearish_inversion_overhead():
    seq = [
        (100, 98, 99),
        (101, 99, 100),  # i-2 (high 101)
        (105, 102, 104),
        (110, 106, 109),  # i: low 106 > 101 -> gap 101..106
        (114, 111, 113),
        (117, 115, 116),  # SWING HIGH (idx 5)
        (115, 112, 113),
        (113, 110, 111),
        (108, 103, 104),  # rotated down, ended below the gap
    ]
    h, low, c = _bars(seq)
    s = scan_swing_fvgs(h, low, c, params=P)
    assert s.fvgs
    bull = [f for f in s.fvgs if f.kind == "BULLISH"]
    assert bull, "a bullish gap into the swing high"
    f = bull[0]
    assert f.inversion_kind == "BEARISH" and f.swing == "HIGH"
    assert f.bottom < f.ce < f.top
    # last close 104 sits below the gap -> it's a bearish array overhead
    assert s.nearest_above is not None and s.nearest_above.inversion_kind == "BEARISH"
    assert s.bias == "BEARISH"


def test_bearish_fvg_into_a_swing_low_is_a_bullish_inversion_below():
    seq = [
        (120, 118, 119),
        (119, 117, 118),  # i-2 (low 117)
        (118, 114, 115),
        (114, 110, 111),  # i: high 114 < 117 -> gap 114..117
        (109, 106, 107),
        (105, 103, 104),  # SWING LOW (idx 5)
        (107, 105, 106),
        (110, 108, 109),
        (116, 113, 115),  # rotated up, ended above the gap
    ]
    h, low, c = _bars(seq)
    s = scan_swing_fvgs(h, low, c, params=P)
    assert s.fvgs
    bear = [f for f in s.fvgs if f.kind == "BEARISH"]
    assert bear and bear[0].inversion_kind == "BULLISH" and bear[0].swing == "LOW"
    assert s.nearest_below is not None and s.nearest_below.inversion_kind == "BULLISH"
    assert s.bias == "BULLISH"


def test_primed_when_price_never_returns_after_leaving():
    seq = [
        (100, 98, 99),
        (101, 99, 100),
        (105, 102, 104),
        (110, 106, 109),  # gap 101..106
        (114, 111, 113),
        (117, 115, 116),  # swing high idx 5
        (115, 113, 114),  # small rotation, stays far above the gap (101..106)
        (113, 111, 112),
        (114, 112, 113),
    ]
    h, low, c = _bars(seq)
    s = scan_swing_fvgs(h, low, c, params=P)
    bull = [f for f in s.fvgs if f.kind == "BULLISH"]
    assert bull and all(f.state == FvgState.PRIMED.value for f in bull)


def test_no_buy_sell_language():
    h, low, c = _bars([(100 + i, 99 + i, 99.5 + i) for i in range(40)])
    s = scan_swing_fvgs(h, low, c)
    blob = repr(s).upper()
    for banned in ("BUY", "SELL", "ENTRY", "TARGET", "STOP LOSS"):
        assert banned not in blob
