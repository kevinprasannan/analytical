"""Candle Range Theory (docs/05 §9d) — reference range + breakout/rejection/
expansion + compression detection."""

from __future__ import annotations

from analytical_core.crt import scan_crt

P = {"scan_bars": 3}


def _bars(seq):
    h = tuple(float(x[0]) for x in seq)
    low = tuple(float(x[1]) for x in seq)
    c = tuple(float(x[2]) for x in seq)
    return h, low, c


def test_insufficient_data_returns_none():
    h, low, c = _bars([(100, 99, 99.5)] * 2)
    assert scan_crt(h, low, c, params=P) is None


def test_no_breakout_is_neutral_and_reports_position():
    # reference candle: 23300-23400; every reacting bar stays inside it
    seq = [
        (23200, 23100, 23150),  # mother
        (23400, 23300, 23350),  # reference
        (23380, 23320, 23350),
        (23370, 23330, 23360),
        (23360, 23320, 23336),  # last close 23336 -> 14pt off the 23350 mid -> INSIDE
    ]
    h, low, c = _bars(seq)
    r = scan_crt(h, low, c, params=P)
    assert r is not None
    assert r.ref_high == 23400 and r.ref_low == 23300 and r.ref_range == 100
    assert r.ref_midpoint == 23350
    assert r.breakout_direction == "NONE"
    assert r.current_position == "INSIDE"
    assert r.signal == "NEUTRAL"
    assert r.is_inside_candle is False  # reference (23300-23400) is NOT inside mother (23100-23200)


def test_break_high_holds_above_is_bullish_continuation():
    seq = [
        (23200, 23100, 23150),
        (23400, 23300, 23350),  # reference: 23300-23400
        (23420, 23390, 23410),  # breaks high, closes outside
        (23460, 23415, 23450),
        (23500, 23455, 23490),  # holds well above, latest close 23490
    ]
    h, low, c = _bars(seq)
    r = scan_crt(h, low, c, params=P)
    assert r is not None
    assert r.breakout_direction == "HIGH"
    assert r.close_outside is True
    assert r.returned_inside is False
    assert r.current_position == "ABOVE_HIGH"
    # expansion 23500 - 23400 = 100 = 1x range -> strong -> RANGE_EXPANSION_UP
    assert r.expansion_points == 100
    assert r.expansion_multiple == 1.0
    assert r.signal == "RANGE_EXPANSION_UP"


def test_break_high_then_close_back_inside_is_high_rejection():
    seq = [
        (23200, 23100, 23150),
        (23400, 23300, 23350),  # reference: 23300-23400
        (23430, 23390, 23415),  # wick breaks high, closes above (still outside)
        (23410, 23360, 23370),
        (23390, 23340, 23350),  # comes back inside -> rejection
    ]
    h, low, c = _bars(seq)
    r = scan_crt(h, low, c, params=P)
    assert r is not None
    assert r.breakout_direction == "HIGH"
    assert r.close_outside is False
    assert r.returned_inside is True
    assert r.signal == "HIGH_REJECTION"


def test_break_low_holds_below_is_bearish_continuation():
    seq = [
        (23400, 23300, 23350),
        (23400, 23300, 23350),  # reference: 23300-23400
        (23310, 23280, 23290),  # breaks low, closes outside
        (23285, 23240, 23250),
        (23245, 23190, 23200),  # holds below
    ]
    h, low, c = _bars(seq)
    r = scan_crt(h, low, c, params=P)
    assert r is not None
    assert r.breakout_direction == "LOW"
    assert r.close_outside is True
    assert r.current_position == "BELOW_LOW"
    assert r.signal in ("BEARISH_CONTINUATION", "RANGE_EXPANSION_DOWN")


def test_small_inside_candle_is_flagged_as_compression():
    seq = [
        (23400, 23300, 23350),  # mother: 23300-23400
        (23380, 23330, 23360),  # reference fully inside mother -> compression
        (23370, 23340, 23355),
        (23375, 23345, 23360),
        (23372, 23342, 23358),  # stays inside the (narrower) reference range too
    ]
    h, low, c = _bars(seq)
    r = scan_crt(h, low, c, params=P)
    assert r is not None
    assert r.is_inside_candle is True
    assert r.breakout_direction == "NONE"
    assert r.signal == "COMPRESSION"


def test_retest_after_breakout_then_continuation():
    seq = [
        (23200, 23100, 23150),
        (23400, 23300, 23350),  # reference: 23300-23400
        (23420, 23395, 23415),  # breaks high
        (23405, 23398, 23400),  # pulls back to retest the level
        (23460, 23410, 23450),  # continues higher, closes outside
    ]
    h, low, c = _bars(seq)
    r = scan_crt(h, low, c, params=P)
    assert r is not None
    assert r.breakout_direction == "HIGH"
    assert r.close_outside is True
    assert r.retested is True


def test_volume_confirms_breakout_when_provided():
    seq = [
        (23200, 23100, 23150),
        (23400, 23300, 23350),
        (23420, 23390, 23410),
        (23460, 23415, 23450),
        (23500, 23455, 23490),
    ]
    h, low, c = _bars(seq)
    vols = (1000, 1000, 5000, 1200, 1200)  # breakout bar volume way above the window average
    r = scan_crt(h, low, c, volumes=vols, params=P)
    assert r is not None
    assert r.volume_confirms is True


def test_ts_is_carried_through_for_reference_and_breakout():
    seq = [
        (23200, 23100, 23150),
        (23400, 23300, 23350),
        (23420, 23390, 23410),
        (23460, 23415, 23450),
        (23500, 23455, 23490),
    ]
    h, low, c = _bars(seq)
    ts = tuple(f"2026-09-16T0{i}:00:00+00:00" for i in range(len(seq)))
    r = scan_crt(h, low, c, ts=ts, params=P)
    assert r is not None
    assert r.reference_ts == ts[1]
    assert r.breakout_ts == ts[2]
