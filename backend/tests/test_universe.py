"""Config-driven tracked-universe selection (docs/04 §2.3)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from analytical_core.enums import InstrumentType, OptionType
from app.instruments.universe import (
    INDEX_PROVIDER_KEY,
    UniverseConfig,
    plan_universe,
)
from app.providers.base import InstrumentRecord

TODAY = date(2026, 8, 29)


def _rec(**kw) -> InstrumentRecord:
    base = dict(provider="upstox", provider_symbol=kw.pop("psym", "x"), exchange="NSE")
    return InstrumentRecord(**base, **kw)


def _index(sym: str) -> InstrumentRecord:
    return _rec(
        instrument_type=InstrumentType.INDEX,
        underlying_symbol=None,
        psym=INDEX_PROVIDER_KEY[sym],
        trading_symbol=sym,
    )


def _fut(sym: str, exp: date, psym: str) -> InstrumentRecord:
    return _rec(
        instrument_type=InstrumentType.FUTURE,
        underlying_symbol=sym,
        expiry_date=exp,
        weekly=False,
        psym=psym,
    )


def _opt(sym: str, exp: date, strike: int, ot: str, *, weekly=True) -> InstrumentRecord:
    return _rec(
        instrument_type=InstrumentType.OPTION,
        underlying_symbol=sym,
        expiry_date=exp,
        strike_price=Decimal(strike),
        option_type=OptionType(ot),
        weekly=weekly,
        psym=f"NSE_FO|{sym}{exp:%y%m%d}{strike}{ot}",
    )


def _nifty_master() -> list[InstrumentRecord]:
    recs = [_index("NIFTY"), _index("BANKNIFTY")]
    for exp, psym in [
        (date(2026, 9, 29), "NSE_FO|NF-SEP"),
        (date(2026, 10, 27), "NSE_FO|NF-OCT"),
        (date(2026, 11, 24), "NSE_FO|NF-NOV"),
    ]:
        recs.append(_fut("NIFTY", exp, psym))
    weeklies = [date(2026, 9, d) for d in (1, 8, 15, 22, 29)] + [date(2026, 10, 6)]
    for exp in weeklies:
        for strike in range(23000, 25600, 50):
            recs.append(_opt("NIFTY", exp, strike, "CE"))
            recs.append(_opt("NIFTY", exp, strike, "PE"))
    # noise: NIFTYNXT50 options must be excluded (different underlying)
    for strike in (24000, 24100):
        recs.append(_opt("NIFTYNXT50", date(2026, 9, 29), strike, "CE"))
    return recs


def test_selects_index_two_futures_and_n_weekly_chains():
    cfg = UniverseConfig(underlyings=("NIFTY",), strike_window=15, max_expiries=5)
    plan = plan_universe(_nifty_master(), cfg, spot_by_symbol={"NIFTY": 24175.0}, today=TODAY)
    m = plan.per_underlying["NIFTY"]
    assert m["future_expiries"] == ["2026-09-29", "2026-10-27"]  # near + next, Nov dropped
    assert m["option_expiries"] == [
        "2026-09-01",
        "2026-09-08",
        "2026-09-15",
        "2026-09-22",
        "2026-09-29",
    ]
    # ATM 24200 ± 15*50 -> [23450, 24950] inclusive = 31 strikes
    assert (m["strike_lo"], m["strike_hi"]) == (23450.0, 24950.0)

    kinds = {}
    for k in plan.tracked_keys:
        kinds[k.split("-")[1]] = kinds.get(k.split("-")[1], 0) + 1
    assert kinds == {"INDEX": 1, "FUT": 2, "OPT": 31 * 2 * 5}
    assert "NIFTYNXT50-OPT-2026-09-24000-CE" not in plan.tracked_keys
    assert all("BANKNIFTY" not in k for k in plan.tracked_keys)  # not configured


def test_strike_window_and_expiry_count_are_config_driven():
    small = plan_universe(
        _nifty_master(),
        UniverseConfig(underlyings=("NIFTY",), strike_window=3, max_expiries=2),
        spot_by_symbol={"NIFTY": 24175.0},
        today=TODAY,
    )
    m = small.per_underlying["NIFTY"]
    assert m["option_expiries"] == ["2026-09-01", "2026-09-08"]
    assert (m["strike_lo"], m["strike_hi"]) == (24050.0, 24350.0)  # ATM ± 3*50
    opt = sum(1 for k in small.tracked_keys if "-OPT-" in k)
    assert opt == 7 * 2 * 2  # 7 strikes, CE+PE, 2 expiries


def test_rolls_forward_when_today_advances():
    master = _nifty_master()
    cfg = UniverseConfig(underlyings=("NIFTY",), strike_window=5, max_expiries=3)
    wk1 = plan_universe(master, cfg, spot_by_symbol={"NIFTY": 24175.0}, today=TODAY)
    wk2 = plan_universe(master, cfg, spot_by_symbol={"NIFTY": 24175.0}, today=date(2026, 9, 2))
    assert wk1.per_underlying["NIFTY"]["option_expiries"][0] == "2026-09-01"
    assert wk2.per_underlying["NIFTY"]["option_expiries"][0] == "2026-09-08"  # Sep-01 rolled off
    assert wk1.tracked_keys != wk2.tracked_keys


def test_no_spot_tracks_index_and_futures_only():
    cfg = UniverseConfig(underlyings=("NIFTY",))
    plan = plan_universe(_nifty_master(), cfg, spot_by_symbol={}, today=TODAY)
    assert not any("-OPT-" in k for k in plan.tracked_keys)
    assert any("-FUT-" in k for k in plan.tracked_keys)
    assert "NIFTY-INDEX" in plan.tracked_keys


def test_from_app_settings_reads_option_selection_keys():
    cfg = UniverseConfig.from_app_settings(
        {
            "option_selection.underlyings": ["NIFTY", "banknifty"],
            "option_selection.strike_window": 20,
            "option_selection.max_expiries": 4,
            "option_selection.strike_step.NIFTY": 50,
            "option_selection.strike_step.BANKNIFTY": 100,
        }
    )
    assert cfg.underlyings == ("NIFTY", "BANKNIFTY")
    assert cfg.strike_window == 20 and cfg.max_expiries == 4
    assert cfg.strike_step == {"NIFTY": 50.0, "BANKNIFTY": 100.0}
