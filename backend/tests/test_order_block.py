"""Order blocks (docs/05 §9a) — deterministic, INDEX/FUTURE PER_TIMEFRAME.

Hand-built golden scenarios + property / provenance checks. Analytical only —
the result names a bias / zone-state / zones, never BUY/SELL.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from analytical_core.enums import AnalysisStatus, OrderBlockBias, OrderBlockZoneState
from analytical_core.indicators import order_block
from analytical_core.params import DEFAULT_PARAMS
from analytical_core.series import OHLCVSeries
from analytical_core.versioning import ALGO_VERSION

T0 = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)
Bar = tuple[float, float, float, float]  # open, high, low, close


def _series(bars: list[Bar], tf: str = "M5") -> OHLCVSeries:
    n = len(bars)
    return OHLCVSeries(
        timeframe=tf,
        ts=tuple(T0 + timedelta(minutes=5 * i) for i in range(n)),
        open=tuple(b[0] for b in bars),
        high=tuple(b[1] for b in bars),
        low=tuple(b[2] for b in bars),
        close=tuple(b[3] for b in bars),
        volume=tuple(1000 + i for i in range(n)),
        is_final=tuple([True] * n),
        expected_grid_len=n,
    )


def _warmup(k: int = 70, px: float = 100.0) -> list[Bar]:
    """Gentle zig-zag so ATR > 0 and no fractal accidentally forms."""
    out: list[Bar] = []
    for i in range(k):
        p = px + (0.3 if i % 2 else -0.3)
        out.append((p, p + 0.25, p - 0.25, p))
    return out


def _green(px: float, body: float = 0.9) -> Bar:
    return (px - body, px + 0.05, px - body - 0.15, px)


def _red(px: float, body: float = 0.9) -> Bar:
    return (px + body, px + body + 0.15, px - 0.05, px)


def _bullish_bos_scenario() -> list[Bar]:
    """Rally to a single peak, pull back on red candles, then a strong rally
    whose close breaks the peak (bullish Break of Structure)."""
    b = _warmup()
    b += [_green(p) for p in (100.6, 101.5, 102.5, 103.4)]
    b.append((103.5, 104.7, 103.3, 104.3))  # the distinct swing-high bar
    b += [_red(p) for p in (103.2, 102.3, 101.5, 100.9)]  # pullback — future OB
    b += [_green(p) for p in (102.4, 103.9, 105.5, 107.2, 109.0, 110.6, 112.1, 113.6)]
    b += [(113.6, 113.8, 113.4, 113.6)] * 6
    return b


def _bearish_bos_scenario() -> list[Bar]:
    b = _warmup()
    b += [_red(p) for p in (99.4, 98.5, 97.5, 96.6)]
    b.append((96.5, 96.7, 95.3, 95.7))  # distinct swing-low bar
    b += [_green(p) for p in (96.8, 97.7, 98.5, 99.1)]  # bounce — future bearish OB
    b += [_red(p) for p in (97.6, 96.1, 94.5, 92.8, 91.0, 89.4, 87.9, 86.4)]
    b += [(86.4, 86.6, 86.2, 86.4)] * 6
    return b


def test_bullish_order_block_from_a_break_of_structure():
    r = order_block(_series(_bullish_bos_scenario()))
    assert r.status is AnalysisStatus.OK
    v = r.values
    bull = [z for z in v["zones"] if z["side"] == "BULLISH"]
    assert bull, v["zones"]
    ob = bull[0]
    assert ob["low"] < ob["high"] <= 104.0  # the block sits below the broken peak
    assert ob["bos_ts"] > ob["formed_ts"]
    assert ob["mitigated"] is False
    assert v["bias"] == OrderBlockBias.BULLISH
    assert v["zone_state"] == OrderBlockZoneState.OUTSIDE


def test_bearish_order_block_mirror():
    v = order_block(_series(_bearish_bos_scenario())).values
    bear = [z for z in v["zones"] if z["side"] == "BEARISH"]
    assert bear, v["zones"]
    assert bear[0]["low"] < bear[0]["high"]
    assert v["bias"] == OrderBlockBias.BEARISH


def test_impulse_gate_rejects_a_weak_break():
    # same structure, but demand an 8x-ATR impulse -> nothing qualifies
    v = order_block(_series(_bullish_bos_scenario()), {"impulse_min_atr": 8.0}).values
    assert v["zones"] == []
    assert v["bias"] == OrderBlockBias.NEUTRAL
    assert v["zone_state"] == OrderBlockZoneState.OUTSIDE


def test_zone_body_vs_range_param():
    s = _series(_bullish_bos_scenario())
    rng = order_block(s, {"zone": "range"}).values["zones"][0]
    body = order_block(s, {"zone": "body"}).values["zones"][0]
    assert (body["high"] - body["low"]) <= (rng["high"] - rng["low"])


def test_mitigation_flag_when_price_returns_into_the_block():
    b = _bullish_bos_scenario()[:-6]  # drop the settle
    # deep retrace straight back down through the demand block, then settle low
    b += [_red(p) for p in (112.0, 110.0, 108.0, 106.0, 104.0, 102.0, 100.5)]
    b += [(100.5, 100.7, 100.3, 100.5)] * 6
    v = order_block(_series(b)).values
    bull = [z for z in v["zones"] if z["side"] == "BULLISH"]
    assert bull and bull[0]["mitigated"] is True
    assert bull[0]["mitigated_ts"] is not None


def test_insufficient_data():
    r = order_block(_series([(100.0, 100.2, 99.8, 100.0)] * 25))
    assert r.status is AnalysisStatus.INSUFFICIENT_DATA
    assert "need >=" in r.values["reason"]


def test_deterministic_and_provenance():
    s = _series(_bullish_bos_scenario())
    a, b = order_block(s), order_block(s)
    assert a.values == b.values
    assert a.meta["params_hash"] == b.meta["params_hash"]
    assert a.meta["algo_version"] == ALGO_VERSION
    assert a.meta["params_id"] == "order_block.v1"
    assert a.meta["params"] == DEFAULT_PARAMS["order_block"]


def test_property_zones_ordered_and_internally_consistent():
    b = _bullish_bos_scenario()[:-6]
    b += [_red(p) for p in (112.0, 110.5, 109.0)]
    b += [_green(p) for p in (110.5, 112.5, 114.5, 116.5, 118.5, 120.0)]
    b += [(120.0, 120.2, 119.8, 120.0)] * 6
    v = order_block(_series(b)).values
    for z in v["zones"]:
        assert z["low"] <= z["mid"] <= z["high"]
        assert z["side"] in ("BULLISH", "BEARISH")
        assert z["age_bars"] >= 0
    assert [z["bos_ts"] for z in v["zones"]] == sorted(
        (z["bos_ts"] for z in v["zones"]), reverse=True
    )


def test_price_inside_a_bearish_block_reads_bearish():
    b = _bearish_bos_scenario()[:-6]
    # rally straight back up into the supply block and stall inside it
    b += [_green(p) for p in (87.5, 89.5, 91.5, 93.5, 95.5, 97.5, 98.6)]
    b += [(98.6, 98.8, 98.4, 98.6)] * 5
    v = order_block(_series(b)).values
    assert v["zones"] and v["zones"][0]["low"] <= v["price"] <= v["zones"][0]["high"]
    assert v["zone_state"] == OrderBlockZoneState.IN_BEARISH
    assert v["bias"] == OrderBlockBias.BEARISH


def test_not_wired_to_buy_sell_language():
    v = order_block(_series(_bullish_bos_scenario())).values
    blob = repr(v).upper()
    for banned in ("BUY", "SELL", "ENTRY", "TARGET", "STOP LOSS", "STOPLOSS"):
        assert banned not in blob
