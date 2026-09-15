"""Major candlestick patterns (docs/05 §9b). Deterministic; descriptive labels."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from analytical_core.enums import AnalysisStatus
from analytical_core.indicators import candles
from analytical_core.params import DEFAULT_PARAMS
from analytical_core.series import OHLCVSeries
from analytical_core.versioning import ALGO_VERSION

T0 = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)
Bar = tuple[float, float, float, float]


def _series(bars: list[Bar]) -> OHLCVSeries:
    n = len(bars)
    return OHLCVSeries(
        timeframe="M5",
        ts=tuple(T0 + timedelta(minutes=5 * i) for i in range(n)),
        open=tuple(b[0] for b in bars),
        high=tuple(b[1] for b in bars),
        low=tuple(b[2] for b in bars),
        close=tuple(b[3] for b in bars),
        volume=tuple(1000 + i for i in range(n)),
        is_final=tuple([True] * n),
        expected_grid_len=n,
    )


def _down(start: float, k: int, step: float = 3.0) -> list[Bar]:
    out, p = [], start
    for _ in range(k):
        o, c = p, p - step
        out.append((o, o + 0.5, c - 0.5, c))
        p = c
    return out


def _up(start: float, k: int, step: float = 3.0) -> list[Bar]:
    out, p = [], start
    for _ in range(k):
        o, c = p, p + step
        out.append((o, c + 0.5, o - 0.5, c))
        p = c
    return out


def _last(v: dict) -> str | None:
    return v["last_pattern"]


def test_insufficient_data():
    r = candles(_series([(100, 101, 99, 100)] * 8))
    assert r.status is AnalysisStatus.INSUFFICIENT_DATA
    assert "need >=" in r.values["reason"]


def test_hammer_in_a_downtrend_is_bullish_on_the_last_bar():
    bars = _down(160.0, 12)  # clear downtrend into ~124
    p = bars[-1][3]
    # a hammer: small (not doji) body near the top, long lower wick
    bars.append((p - 1.5, p + 0.3, p - 6.0, p))
    v = candles(_series(bars)).values
    assert _last(v) == "HAMMER" and v["last_bias"] == "BULLISH"
    assert v["on_last_bar"] is True and v["bias"] == "BULLISH"


def test_shooting_star_in_an_uptrend_is_bearish():
    bars = _up(100.0, 12)
    p = bars[-1][3]
    bars.append((p + 2.0, p + 8.0, p + 0.3, p + 0.5))  # long upper wick, small body at the low
    v = candles(_series(bars)).values
    assert _last(v) == "SHOOTING_STAR" and v["last_bias"] == "BEARISH"


def test_bullish_engulfing_in_a_downtrend():
    bars = _down(160.0, 12)
    p = bars[-1][3]
    bars.append((p + 0.2, p + 0.6, p - 2.2, p - 2.0))  # small down bar
    prev = bars[-1]
    bars.append((prev[3] - 0.3, prev[0] + 3.5, prev[3] - 0.6, prev[0] + 3.0))  # engulfs it, up
    v = candles(_series(bars)).values
    assert _last(v) == "BULLISH_ENGULFING" and v["last_bias"] == "BULLISH"


def test_bearish_engulfing_in_an_uptrend():
    bars = _up(100.0, 12)
    p = bars[-1][3]
    bars.append((p - 0.2, p + 2.2, p - 0.6, p + 2.0))  # small up bar
    prev = bars[-1]
    bars.append((prev[3] + 0.3, prev[3] + 0.6, prev[0] - 3.5, prev[0] - 3.0))  # engulfs it, down
    v = candles(_series(bars)).values
    assert _last(v) == "BEARISH_ENGULFING" and v["last_bias"] == "BEARISH"


def test_doji_is_neutral():
    bars = _series(_down(120.0, 12) + [(100.0, 103.0, 97.0, 100.05)])
    v = candles(bars).values
    assert v["last_pattern"] == "DOJI" and v["last_bias"] == "NEUTRAL"


def test_gravestone_doji_in_an_uptrend_is_bearish():
    bars = _up(100.0, 12)  # clear uptrend
    p = bars[-1][3]
    # tiny body pinned near the low, long upper wick: (open, high, low, close)
    bars.append((p, p + 10.0, p - 0.15, p - 0.1))
    v = candles(_series(bars)).values
    assert v["last_pattern"] == "GRAVESTONE_DOJI" and v["last_bias"] == "BEARISH"
    assert v["last_strength"] == "STRONG"


def test_dragonfly_doji_in_a_downtrend_is_bullish():
    bars = _down(160.0, 12)  # clear downtrend
    p = bars[-1][3]
    # tiny body pinned near the high, long lower wick: (open, high, low, close)
    bars.append((p, p + 0.05, p - 10.0, p - 0.05))
    v = candles(_series(bars)).values
    assert v["last_pattern"] == "DRAGONFLY_DOJI" and v["last_bias"] == "BULLISH"
    assert v["last_strength"] == "STRONG"


def test_marubozu_is_directional():
    bars = _series([(100, 101, 99, 100)] * 12 + [(100.0, 110.05, 99.95, 110.0)])
    v = candles(bars).values
    assert v["last_pattern"] == "MARUBOZU" and v["last_bias"] == "BULLISH"


def test_frozen_tape_then_jump_is_not_scored():
    # a genuine uptrend, then the feed carries the same LTP forward for several
    # bars (a provider snapshot stall — see NSE_INDEX near the session close),
    # then a single-bar "catch-up" jump that would otherwise read as a strong
    # marubozu. The jump bar must not be scored as a pattern.
    bars = _up(100.0, 12)
    frozen = bars[-1][3]
    bars += [(frozen, frozen, frozen, frozen)] * 3  # 3 identical zero-range bars
    bars.append((frozen, frozen, frozen - 5.0, frozen - 5.0))  # the "jump" bar
    v = candles(_series(bars)).values
    assert v["on_last_bar"] is False
    assert v["last_pattern"] is None
    assert v["bias"] == "NEUTRAL"
    assert all(p["bars_ago"] != 0 for p in v["patterns"])


def test_frozen_tape_below_the_minimum_run_is_still_scored():
    # only 1 flat bar before the jump — below frozen_run_min_bars (2) — so the
    # jump bar is scored normally (a single stale print is not enough to flag).
    bars = _up(100.0, 12)
    frozen = bars[-1][3]
    bars.append((frozen, frozen, frozen, frozen))  # 1 identical zero-range bar
    bars.append((frozen, frozen, frozen - 5.0, frozen - 5.0))  # the "jump" bar
    v = candles(_series(bars)).values
    assert v["on_last_bar"] is True
    assert v["last_pattern"] == "MARUBOZU"


def test_morning_star_three_bar_bullish():
    bars = _down(160.0, 12)
    a = bars[-1][3]
    bars.append((a, a + 0.4, a - 8.0, a - 7.5))  # long bearish
    b = bars[-1][3]
    bars.append((b - 0.2, b + 0.6, b - 0.9, b - 0.4))  # small star
    c = bars[-1][3]
    bars.append((c + 0.2, c + 7.5, c - 0.3, c + 7.0))  # long bullish back over bar1 midpoint
    v = candles(_series(bars)).values
    assert v["last_pattern"] == "MORNING_STAR" and v["last_bias"] == "BULLISH"


def test_no_pattern_leaves_bias_neutral():
    # a quiet drift with no clean pattern shape
    bars = _series(
        [
            (100 + i * 0.2, 100 + i * 0.2 + 0.7, 100 + i * 0.2 - 0.7, 100 + i * 0.2 + 0.35)
            for i in range(30)
        ]
    )
    v = candles(bars).values
    assert v["bias"] == "NEUTRAL" and v["last_pattern"] is None


def test_bars_ago_and_scan_window():
    bars = _down(160.0, 12)
    p = bars[-1][3]
    bars.append((p - 1.5, p + 0.3, p - 6.0, p))  # hammer here
    bars += [
        (p + i, p + i + 0.6, p + i - 0.6, p + i + 0.3) for i in range(1, 4)
    ]  # 3 quiet bars after
    v = candles(_series(bars)).values
    hammer = next((x for x in v["patterns"] if x["pattern"] == "HAMMER"), None)
    assert hammer is not None and hammer["bars_ago"] == 3
    assert v["on_last_bar"] is False


def test_deterministic_and_provenance():
    bars = _series(_down(160.0, 12) + [(124.0, 124.8, 118.0, 124.5)])
    a, b = candles(bars), candles(bars)
    assert a.values == b.values
    assert a.meta["algo_version"] == ALGO_VERSION
    assert a.meta["params_id"] == "candles.v1"
    assert a.meta["params"] == DEFAULT_PARAMS["candles"]


def test_no_buy_sell_language():
    v = candles(_series(_down(160.0, 12) + [(124.0, 124.8, 118.0, 124.5)])).values
    blob = repr(v).upper()
    for banned in ("BUY", "SELL", "ENTRY", "TARGET", "STOP LOSS"):
        assert banned not in blob
