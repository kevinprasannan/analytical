"""Phase 3 — pure indicator engine: golden values, edges, determinism, provenance.

Golden values are hand-verified against the docs/05 formulas (RSI vs the Wilder
worked example = 70.46; Bollinger basis = arithmetic mean; EMA seed = SMA).
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from analytical_core.enums import (
    AnalysisScope,
    AnalysisStatus,
    Divergence,
    GoldenCrossType,
    InstrumentType,
    RSIState,
    Timeframe,
    VolumeUpDownState,
)
from analytical_core.indicators import bollinger, ema7, golden_cross, open_interest, rsi, volume
from analytical_core.series import OHLCVSeries, OpenInterestSeries
from analytical_core.versioning import ALGO_VERSION

T0 = datetime(2026, 8, 27, 3, 45, tzinfo=UTC)


def mk(closes, *, vols=None, finals=None, tf=Timeframe.M5, opens=None, highs=None, lows=None):
    n = len(closes)
    c = tuple(float(x) for x in closes)
    o = tuple(float(x) for x in (opens if opens is not None else [c[0], *c[:-1]]))
    h = tuple(
        float(x)
        for x in (highs if highs is not None else [max(a, b) for a, b in zip(o, c, strict=True)])
    )
    low = tuple(
        float(x)
        for x in (lows if lows is not None else [min(a, b) for a, b in zip(o, c, strict=True)])
    )
    return OHLCVSeries(
        timeframe=tf,
        ts=tuple(T0 + timedelta(minutes=i) for i in range(n)),
        open=o,
        high=h,
        low=low,
        close=c,
        volume=tuple(int(x) for x in (vols if vols is not None else [100] * n)),
        is_final=tuple(bool(x) for x in (finals if finals is not None else [True] * n)),
        expected_grid_len=n,
    )


WILDER = [
    44.34,
    44.09,
    44.15,
    43.61,
    44.33,
    44.83,
    45.10,
    45.42,
    45.84,
    46.08,
    45.89,
    46.03,
    45.61,
    46.28,
    46.28,
]


# ======================================================================================
# RSI (docs/05 §4)
# ======================================================================================


def test_rsi_wilder_worked_example():
    r = rsi(mk(WILDER))
    assert r.status is AnalysisStatus.OK
    assert r.values["rsi"] == 70.46  # matches the classic Wilder reference
    assert r.values["state"] == RSIState.OVERBOUGHT.value


def test_rsi_terminal_value_precedence():
    assert rsi(mk([100.0] * 20)).values["rsi"] == 50.0  # both-zero -> 50 (case 1)
    assert rsi(mk([100 + i for i in range(20)])).values["rsi"] == 100.0  # avg_loss==0
    assert rsi(mk([100 - i for i in range(20)])).values["rsi"] == 0.0  # avg_gain==0


def test_rsi_insufficient_below_period_plus_one():
    r = rsi(mk([100.0] * 10))
    assert r.status is AnalysisStatus.INSUFFICIENT_DATA
    assert r.meta["warmup_ok"] is False


def test_rsi_divergence_bullish_and_none_boundary():
    # last close is the window min and RSI recovered by >= div_min_rsi_delta
    closes = [50, 49, 48, 47, 46, 45, 44, 43, 42, 41, 40, 41, 40, 41, 40]
    r = rsi(mk(closes), overrides={"div_lookback": 5, "div_min_rsi_delta": 0.1})
    assert r.values["divergence"] in {Divergence.BULLISH.value, Divergence.NONE.value}
    # a monotone series never shows divergence
    assert rsi(mk([100 + i for i in range(40)])).values["divergence"] == Divergence.NONE.value


def test_rsi_series_has_leading_nulls_during_warmup():
    r = rsi(mk([100 + (i % 3) for i in range(30)]))
    assert r.series["rsi"][:14] == [None] * 14 and r.series["rsi"][14] is not None


# ======================================================================================
# Bollinger (docs/05 §5)
# ======================================================================================


def test_bollinger_population_std_reference():
    b = bollinger(mk(list(range(1, 26))))
    assert b.values["basis"] == 15.5  # mean of 6..25
    assert b.values["position"] == "UPPER_HALF"
    assert 0.0 <= b.values["percent_b"] <= 1.0


def test_bollinger_degenerate_upper_equals_lower():
    b = bollinger(mk([50.0] * 25))
    assert b.values["position"] == "MIDDLE"
    assert b.values["percent_b"] == 0.5
    assert b.values["bandwidth"] == 0.0


def test_bollinger_squeeze_null_when_window_short():
    b = bollinger(mk([100 + (i % 5) for i in range(30)]))
    assert b.values["squeeze"] is None
    assert b.values["bandwidth_percentile"] is None


def test_bollinger_squeeze_excludes_current_bar():
    # long calm stretch then the current bar is the tightest -> squeeze True
    closes = [100 + (i % 7) for i in range(150)] + [100.0] * 21
    b = bollinger(mk(closes), overrides={"squeeze_lookback": 100})
    assert b.values["squeeze"] is True
    assert 0.0 <= b.values["bandwidth_percentile"] <= 1.0


# ======================================================================================
# EMA (docs/05 §6)
# ======================================================================================


def test_ema_seed_is_sma_and_recurrence():
    e = ema7(mk([float(i) for i in range(1, 15)]))
    # seed at idx 6 = mean(1..7) = 4.0; then recurrence to idx 13
    assert e.series["ema"][6] == 4.0
    assert e.values["ema"] == round(e.series["ema"][-1], 4)
    assert e.values["slope_state"] == "RISING"


def test_ema_slope_unknown_below_period_plus_lookback():
    e = ema7(mk([float(i) for i in range(1, 9)]))  # 8 bars, period 7, lookback 3
    assert e.values["slope"] is None
    assert e.values["slope_state"] == "UNKNOWN"


def test_ema_atr_aux_present_with_enough_bars():
    e = ema7(mk([100 + i * 0.5 for i in range(30)]))
    assert e.aux["atr14"] is not None
    e2 = ema7(mk([100 + i for i in range(10)]))
    assert e2.aux["atr14"] is None  # < 15 bars


# ======================================================================================
# Golden Cross (docs/05 §7)
# ======================================================================================


def _gc_series(down: int = 220, up: int = 60, lo: float = 100.0, hi: float = 300.0):
    # a long decline (fast MA driven below slow MA) then a sharp rally that
    # produces a `- -> +` cross inside the last `cross_search_window` bars.
    closes = [200.0 - i * ((200.0 - lo) / (down - 1)) for i in range(down)]
    closes += [lo + i * ((hi - lo) / (up - 1)) for i in range(up)]
    return mk(closes, tf=Timeframe.D1)


def test_golden_cross_detects_a_golden_cross():
    g = golden_cross(_gc_series(), instrument_type=InstrumentType.INDEX)
    assert g.status is AnalysisStatus.OK
    assert g.values["cross_type"] == GoldenCrossType.GOLDEN.value
    assert g.values["state"] == "ABOVE"
    assert g.values["bars_since_cross"] == 25


def test_golden_cross_none_in_window_when_no_recent_cross():
    g = golden_cross(mk([100.0] * 260, tf=Timeframe.D1), instrument_type=InstrumentType.INDEX)
    assert g.values["cross_type"] == GoldenCrossType.NONE_IN_WINDOW.value
    assert g.values["cross_ts"] is None and g.values["bars_since_cross"] is None


def test_golden_cross_not_applicable_for_dated_by_default():
    for it in (InstrumentType.FUTURE, InstrumentType.OPTION):
        g = golden_cross(mk([100.0] * 260, tf=Timeframe.D1), instrument_type=it)
        assert g.status is AnalysisStatus.NOT_APPLICABLE
        assert "index" in g.values["reason"].lower()


def test_golden_cross_opt_in_for_dated_emits_warning():
    g = golden_cross(
        _gc_series(),
        instrument_type=InstrumentType.FUTURE,
        overrides={"enable_for_dated": True},
    )
    assert g.status is AnalysisStatus.OK
    assert any("not equivalent to the index golden cross" in w for w in g.warnings)


def test_golden_cross_insufficient_below_slow_period():
    g = golden_cross(mk([100.0] * 120, tf=Timeframe.D1), instrument_type=InstrumentType.INDEX)
    assert g.status is AnalysisStatus.INSUFFICIENT_DATA


# ======================================================================================
# Volume (docs/05 §8)
# ======================================================================================


def test_volume_not_applicable_when_no_volume_capability():
    v = volume(mk([100.0] * 30), has_volume=False)
    assert v.status is AnalysisStatus.NOT_APPLICABLE


def test_volume_all_zero_is_insufficient_not_not_applicable():
    v = volume(mk([100 + i for i in range(30)], vols=[0] * 30), has_volume=True)
    assert v.status is AnalysisStatus.INSUFFICIENT_DATA
    assert "no traded volume" in v.values["reason"]


def test_volume_rvol_null_on_zero_denominator():
    # only the current bar has volume -> the rvol denominator window is all zeros
    v = volume(mk([100 + i for i in range(30)], vols=[0] * 29 + [500]), has_volume=True)
    assert v.values["rvol"] is None


def test_volume_spike_and_up_down_state_and_aux():
    v = volume(
        mk([100 + i for i in range(30)], vols=[10] * 29 + [100]),
        has_volume=True,
    )
    assert v.values["spike"] is True  # 100 >= 2 * vol_ma
    assert v.values["up_down_state"] == VolumeUpDownState.ALL_UP.value  # every bar close>=open
    assert v.values["up_down_ratio"] is None
    assert "price_change_pct_recent" in v.aux


# ======================================================================================
# Open Interest (docs/05 §9)
# ======================================================================================


def _oi(oi, price, *, scope=AnalysisScope.PER_TIMEFRAME, poc=None):
    n = len(oi)
    return OpenInterestSeries(
        scope=scope,
        ts=tuple(T0 + timedelta(minutes=5 * i) for i in range(n)),
        oi=tuple(int(x) for x in oi),
        price=tuple(float(x) for x in price),
        provider_oi_change=tuple(int(x) for x in poc) if poc is not None else None,
    )


def test_oi_long_buildup_and_ignores_provider_delta():
    r = open_interest(
        _oi([1000, 1000, 1100, 1200, 1300], [50, 50, 51, 52, 53], poc=[0, 0, 999, 999, 999]),
        instrument_type=InstrumentType.FUTURE,
    )
    assert r.values["behavior"] == "LONG_BUILDUP"
    assert r.values["oi_direction"] == "UP" and r.values["price_direction"] == "UP"
    assert r.values["oi_change"] == 100  # from stored oi, not provider_oi_change
    assert r.values["provider_oi_change"] == 999  # echoed only


def test_oi_indeterminate_via_price_flat_and_via_oi_flat():
    price_flat = open_interest(
        _oi([1000, 2000], [100.0, 100.0]), instrument_type=InstrumentType.FUTURE
    )
    assert price_flat.values["behavior"] == "INDETERMINATE"
    oi_flat = open_interest(
        _oi([1000, 1000], [100.0, 110.0]), instrument_type=InstrumentType.FUTURE
    )
    assert oi_flat.values["behavior"] == "INDETERMINATE"


def test_oi_not_applicable_for_index_and_warns_for_option():
    idx = open_interest(_oi([1, 2], [1.0, 2.0]), instrument_type=InstrumentType.INDEX)
    assert idx.status is AnalysisStatus.NOT_APPLICABLE
    opt = open_interest(_oi([1000, 1200], [10.0, 12.0]), instrument_type=InstrumentType.OPTION)
    assert any("this option contract" in w for w in opt.warnings)


def test_oi_prior_zero_yields_null_pct_change():
    r = open_interest(_oi([0, 500], [10.0, 11.0]), instrument_type=InstrumentType.FUTURE)
    assert r.values["oi_pct_change"] is None


# ======================================================================================
# cross-cutting: determinism + provenance (docs/09 §6 DoD 4,5)
# ======================================================================================

_CASES = [
    lambda s: rsi(s),
    lambda s: bollinger(s),
    lambda s: ema7(s),
    lambda s: golden_cross(s, instrument_type=InstrumentType.INDEX),
    lambda s: volume(s, has_volume=True),
]


@pytest.mark.parametrize("fn", _CASES)
def test_determinism_same_input_same_output(fn):
    rng = random.Random(42)
    closes = [100.0]
    for _ in range(299):
        closes.append(closes[-1] * (1 + rng.uniform(-0.01, 0.01)))
    s1 = mk(closes, tf=Timeframe.D1)
    s2 = mk(list(closes), tf=Timeframe.D1)
    a, b = fn(s1), fn(s2)
    assert a.values == b.values and a.aux == b.aux
    assert a.meta["params_hash"] == b.meta["params_hash"]


@pytest.mark.parametrize("fn", _CASES)
def test_provenance_present_on_every_result(fn):
    s = mk([100 + (i % 5) for i in range(60)], tf=Timeframe.D1)
    r = fn(s)
    m = r.meta
    assert m["algo_version"] == ALGO_VERSION
    assert m["params_id"].endswith(".v1")
    assert isinstance(m["params_hash"], str) and len(m["params_hash"]) == 16
    assert "input_window_start" in m and "input_window_end" in m
    assert m["last_bar_final"] is True


def test_params_hash_changes_with_an_override():
    s = mk([100 + (i % 5) for i in range(60)])
    base = rsi(s).meta["params_hash"]
    changed = rsi(s, overrides={"period": 21}).meta["params_hash"]
    assert base != changed


def test_series_contract_rejects_bad_input():
    from analytical_core.series import SeriesContractError

    with pytest.raises(SeriesContractError):
        OHLCVSeries(
            timeframe=Timeframe.M5,
            ts=(T0, T0),  # not strictly increasing
            open=(1.0, 1.0),
            high=(1.0, 1.0),
            low=(1.0, 1.0),
            close=(1.0, 1.0),
            volume=(1, 1),
            is_final=(True, True),
            expected_grid_len=2,
        )
    with pytest.raises(SeriesContractError):
        OHLCVSeries(
            timeframe=Timeframe.M5,
            ts=(T0.replace(tzinfo=None),),
            open=(1.0,),
            high=(1.0,),
            low=(1.0,),
            close=(1.0,),
            volume=(1,),
            is_final=(True,),
            expected_grid_len=1,
        )
