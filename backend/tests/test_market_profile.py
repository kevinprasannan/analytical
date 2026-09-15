"""Market Profile engine — period model, bucketing, POC/VA, shape (docs/05 §10)."""

from __future__ import annotations

import math
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from analytical_core.enums import InstrumentType, Timeframe
from analytical_core.market_profile import MarketProfileConfig, market_profile, session_periods
from analytical_core.market_profile.engine import resolve_bin_size
from analytical_core.series import OHLCVSeries

IST = ZoneInfo("Asia/Kolkata")


def _win(open_ist=time(9, 15), close_ist=time(15, 30), d="2026-08-27"):
    day = datetime.fromisoformat(f"{d}T00:00:00").date()
    o = datetime.combine(day, open_ist, tzinfo=IST).astimezone(UTC)
    c = datetime.combine(day, close_ist, tzinfo=IST).astimezone(UTC)
    return o, c, day


def _series(closes, *, o_utc, span_min=5, spread=6.0, vols=None):
    n = len(closes)
    ts = tuple(o_utc + timedelta(minutes=span_min * i) for i in range(n))
    c = tuple(float(x) for x in closes)
    op = tuple([c[0], *c[:-1]])
    hi = tuple(m + spread for m in c)
    lo = tuple(m - spread for m in c)
    v = tuple(int(x) for x in (vols or [1000 + i for i in range(n)]))
    return OHLCVSeries(Timeframe.M5, ts, op, hi, lo, c, v, tuple([True] * n), n)


# ======================================================================================
# period generation (docs/05 §10.2)
# ======================================================================================


def test_default_session_reproduces_a_to_m():
    o, c, _ = _win()
    ps = session_periods(o, c, 30, "KEEP")
    assert "".join(p.letter for p in ps) == "ABCDEFGHIJKLM"
    assert ps[-1].is_partial and (ps[-1].end - ps[-1].start) == timedelta(minutes=15)


@pytest.mark.parametrize(("tpo", "expected_full"), [(20, 18), (30, 12), (60, 6)])
def test_period_count_by_tpo_minutes(tpo, expected_full):
    o, c, _ = _win()
    ps = session_periods(o, c, tpo, "KEEP")
    full = [p for p in ps if not p.is_partial]
    assert len(full) == expected_full


def test_shortened_session_period_generation():
    o, c, _ = _win(close_ist=time(13, 0))  # 225 minutes
    ps = session_periods(o, c, 30, "KEEP")
    assert len([p for p in ps if not p.is_partial]) == 7  # floor(225/30)
    assert ps[-1].is_partial and (ps[-1].end - ps[-1].start) == timedelta(minutes=15)


def test_partial_period_policy_drop_and_merge():
    o, c, _ = _win()
    assert len(session_periods(o, c, 30, "DROP")) == 12
    merged = session_periods(o, c, 30, "MERGE_PREV")
    assert len(merged) == 12
    assert (merged[-1].end - merged[-1].start) == timedelta(minutes=45)


# ======================================================================================
# bin size (docs/05 §10.4)
# ======================================================================================


def test_bin_size_index_uses_underlying_increment():
    cfg = MarketProfileConfig()
    bs = resolve_bin_size(
        instrument_type=InstrumentType.INDEX,
        config=cfg,
        price_ref=24000.0,
        tick_size=0.05,
        underlying_symbol="NIFTY",
        explicit=None,
    )
    assert bs == 5.0  # increment for NIFTY; 24000*0.00025=6 rounds to 5


def test_bin_size_explicit_wins():
    bs = resolve_bin_size(
        instrument_type=InstrumentType.INDEX,
        config=MarketProfileConfig(),
        price_ref=24000.0,
        tick_size=0.05,
        underlying_symbol="NIFTY",
        explicit=2.5,
    )
    assert bs == 2.5


def test_bin_size_option_is_pct_of_premium_or_tick():
    bs = resolve_bin_size(
        instrument_type=InstrumentType.OPTION,
        config=MarketProfileConfig(),
        price_ref=120.0,
        tick_size=0.05,
        underlying_symbol="NIFTY",
        explicit=None,
    )
    assert bs == pytest.approx(1.2)  # 1% of 120


# ======================================================================================
# full profile: POC / value area / IB / close flags
# ======================================================================================


def _hump(n=75, centre=24000.0, amp=150.0):
    return [centre + amp * math.exp(-((i - n / 2) ** 2) / (2 * (n / 6) ** 2)) for i in range(n)]


def test_full_session_profile_is_ok_with_poc_va_ib():
    o, c, d = _win()
    s = _series(_hump(), o_utc=o, spread=8.0)
    out = market_profile(
        s,
        config=MarketProfileConfig(),
        session_open=o,
        session_close=c,
        session_date=d,
        instrument_type=InstrumentType.INDEX,
        has_volume=True,
        price_ref=24000.0,
        underlying_symbol="NIFTY",
        now=c + timedelta(minutes=5),
    )
    assert out.status == "OK"
    assert set(out.profiles) == {"TPO", "VOLUME"}
    t = out.profiles["TPO"]
    assert t.val <= t.poc <= t.vah
    assert t.session_low <= t.poc <= t.session_high
    assert t.ib_high is not None and t.ib_low is not None and t.ib_complete
    assert t.n_periods_elapsed == t.n_periods_total == 13
    assert t.is_session_complete is True
    # value area covers ~70% of TPOs
    metric_total = sum(b["tpo_count"] for b in t.bins)
    va_total = sum(b["tpo_count"] for b in t.bins if t.val <= b["price_low"] <= t.vah)
    assert 0.60 <= va_total / metric_total <= 0.95


def test_tpo_bins_carry_the_letter_profile():
    # each TPO bin's `letters` string is the classic letter-profile read — the
    # periods that printed at that price, chronological order, one char each
    o, c, d = _win()
    s = _series(_hump(), o_utc=o, spread=8.0)
    out = market_profile(
        s,
        config=MarketProfileConfig(),
        session_open=o,
        session_close=c,
        session_date=d,
        instrument_type=InstrumentType.INDEX,
        has_volume=True,
        price_ref=24000.0,
        underlying_symbol="NIFTY",
        now=c + timedelta(minutes=5),
    )
    t = out.profiles["TPO"]
    poc_bin = next(b for b in t.bins if b["price_low"] == t.poc)
    # the POC is the busiest price — should carry more than one period's letter
    assert len(poc_bin["letters"]) == poc_bin["tpo_count"] >= 2
    assert poc_bin["letters"] == "".join(sorted(poc_bin["letters"]))  # chronological (A<B<...)
    for b in t.bins:
        assert len(b["letters"]) == b["tpo_count"]
        assert set(b["letters"]) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
    # the volume profile has no letters — it isn't a TPO read
    v = out.profiles["VOLUME"]
    assert all("letters" not in b for b in v.bins)


def test_value_area_single_vs_pair_expansion_differ_or_equal():
    o, c, d = _win()
    s = _series(_hump(), o_utc=o, spread=8.0)
    kw = dict(
        session_open=o,
        session_close=c,
        session_date=d,
        instrument_type=InstrumentType.INDEX,
        has_volume=False,
        price_ref=24000.0,
        underlying_symbol="NIFTY",
        now=c + timedelta(minutes=5),
    )
    pair = market_profile(s, config=MarketProfileConfig(va_expansion="PAIR"), **kw).profiles["TPO"]
    single = market_profile(s, config=MarketProfileConfig(va_expansion="SINGLE"), **kw).profiles[
        "TPO"
    ]
    assert pair.poc == single.poc
    assert (pair.vah - pair.val) >= (single.vah - single.val) - 1e-9


def test_too_few_periods_is_insufficient():
    o, c, d = _win()
    s = _series(_hump(10), o_utc=o)  # ~50 min -> ~2 periods
    out = market_profile(
        s,
        config=MarketProfileConfig(),
        session_open=o,
        session_close=c,
        session_date=d,
        instrument_type=InstrumentType.INDEX,
        has_volume=False,
        price_ref=24000.0,
        underlying_symbol="NIFTY",
        now=o + timedelta(minutes=40),
    )
    assert out.status == "INSUFFICIENT_DATA" and "periods elapsed" in out.reason


def test_tiny_range_is_insufficient_min_bins():
    o, c, d = _win()
    s = _series([24000.0 + (i % 2) * 0.5 for i in range(75)], o_utc=o, spread=0.4)
    out = market_profile(
        s,
        config=MarketProfileConfig(),
        session_open=o,
        session_close=c,
        session_date=d,
        instrument_type=InstrumentType.INDEX,
        has_volume=False,
        price_ref=24000.0,
        underlying_symbol="NIFTY",
        now=c,
    )
    assert out.status == "INSUFFICIENT_DATA" and "range too small" in out.reason


# ======================================================================================
# shape classifier (docs/05 §10.8)
# ======================================================================================


def test_trend_up_shape():
    o, c, d = _win()
    s = _series([24000.0 + 4.0 * i for i in range(75)], o_utc=o, spread=6.0)  # steady climb
    out = market_profile(
        s,
        config=MarketProfileConfig(),
        session_open=o,
        session_close=c,
        session_date=d,
        instrument_type=InstrumentType.INDEX,
        has_volume=False,
        price_ref=24000.0,
        underlying_symbol="NIFTY",
        now=c,
    )
    assert out.status == "OK"
    assert out.profiles["TPO"].profile_shape in {"TREND_UP", "P_SHAPE", "NORMAL"}


def test_determinism_same_input_same_output():
    o, c, d = _win()
    s1 = _series(_hump(), o_utc=o)
    s2 = _series(_hump(), o_utc=o)
    kw = dict(
        config=MarketProfileConfig(),
        session_open=o,
        session_close=c,
        session_date=d,
        instrument_type=InstrumentType.INDEX,
        has_volume=True,
        price_ref=24000.0,
        underlying_symbol="NIFTY",
        now=c,
    )
    a = market_profile(s1, **kw).profiles["TPO"]
    b = market_profile(s2, **kw).profiles["TPO"]
    assert (a.poc, a.vah, a.val, a.profile_shape, a.bin_size) == (
        b.poc,
        b.vah,
        b.val,
        b.profile_shape,
        b.bin_size,
    )
    assert a.bins == b.bins


# ======================================================================================
# MarketProfileConfig.from_app_settings — app_settings merge (docs/05 §10.1)
# ======================================================================================


def test_mp_from_app_settings_none_is_defaults():
    assert (
        MarketProfileConfig.from_app_settings(None).hashable() == MarketProfileConfig().hashable()
    )
    assert MarketProfileConfig.from_app_settings({}).hashable() == MarketProfileConfig().hashable()


def test_mp_from_app_settings_overrides_and_casts():
    cfg = MarketProfileConfig.from_app_settings(
        {"market_profile.tpo_minutes": "60", "market_profile.value_area_pct": "0.8"}
    )
    assert cfg.tpo_minutes == 60
    assert cfg.value_area_pct == 0.8
    assert cfg.ib_periods == MarketProfileConfig().ib_periods
    assert cfg.hashable() != MarketProfileConfig().hashable()


def test_mp_from_app_settings_larger_tpo_yields_fewer_periods():
    o, c, _ = _win()
    cfg60 = MarketProfileConfig.from_app_settings({"market_profile.tpo_minutes": 60})
    default_periods = len(session_periods(o, c, MarketProfileConfig().tpo_minutes, "KEEP"))
    wide_periods = len(session_periods(o, c, cfg60.tpo_minutes, "KEEP"))
    assert wide_periods < default_periods
