"""Phase 2.2 — deterministic validation (§4, §9, §11)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from analytical_core.enums import ExpiryKind, InstrumentSegment, InstrumentType, OptionType
from app.instruments.validation import validate
from app.providers.base import InstrumentRecord
from app.providers.upstox.instrument_master import records_from_master
from tests.conftest import UPSTOX_MASTER_DIR

SAMPLE = UPSTOX_MASTER_DIR / "nse_master_sample.json"
BAD_ROWS = UPSTOX_MASTER_DIR / "nse_master_bad_rows.json"


def _rec(**kw) -> InstrumentRecord:
    base = dict(
        provider="upstox",
        provider_symbol="NSE_FO|1",
        instrument_type=InstrumentType.OPTION,
        underlying_symbol="NIFTY",
        exchange="NSE",
        segment=InstrumentSegment.OPT,
        underlying_provider_key="NSE_INDEX|Nifty 50",
        expiry_date=date(2026, 9, 4),
        weekly=True,
        option_type=OptionType.CE,
        strike_price=Decimal("24000"),
        lot_size=65,
        tick_size=Decimal("5"),
        trading_symbol="NIFTY 24000 CE",
    )
    base.update(kw)
    return InstrumentRecord(**base)


def test_sample_accepts_index_futures_options():
    records, norm_rej = records_from_master(SAMPLE)
    accepted, quarantined = validate(records)
    keys = {c.contract_key for c in accepted}
    assert "NIFTY-INDEX" in keys and "BANKNIFTY-INDEX" in keys
    assert "NIFTY-FUT-2026-09" in keys and "NIFTY-FUT-2026-10" in keys
    assert "NIFTY-OPT-2026-09-04-24000-CE" in keys  # weekly
    assert "NIFTY-OPT-2026-09-24000-CE" in keys  # monthly
    assert "BANKNIFTY-OPT-2026-09-54000-CE" in keys
    # weekly-flag-missing option -> quarantined, not guessed
    assert any("cannot classify expiry_kind" in q.reason for q in quarantined)


def test_expiry_kind_from_weekly_flag_only():
    assert validate([_rec(weekly=True)])[0][0].expiry_kind is ExpiryKind.WEEKLY
    assert validate([_rec(weekly=False)])[0][0].expiry_kind is ExpiryKind.MONTHLY
    # never QUARTERLY — provider gives no signal for it
    assert validate([_rec(weekly=False)])[0][0].expiry_kind is not ExpiryKind.QUARTERLY


def test_missing_weekly_on_derivative_is_quarantined():
    acc, q = validate([_rec(weekly=None)])
    assert acc == []
    assert q[0].reason == "cannot classify expiry_kind: provider 'weekly' flag absent/invalid"


def test_non_expiring_index_row():
    idx = InstrumentRecord(
        provider="upstox",
        provider_symbol="NSE_INDEX|Nifty 50",
        instrument_type=InstrumentType.INDEX,
        underlying_symbol=None,
        exchange="NSE",
        segment=InstrumentSegment.INDEX,
        trading_symbol="NIFTY",
        name="Nifty 50",
    )
    (c,), q = validate([idx])
    assert q == []
    assert c.contract_key == "NIFTY-INDEX"
    assert c.expiry_kind is None and c.has_intraday_oi is False


def test_index_with_expiry_is_rejected():
    idx = InstrumentRecord(
        provider="upstox",
        provider_symbol="X",
        instrument_type=InstrumentType.INDEX,
        underlying_symbol=None,
        exchange="NSE",
        segment=InstrumentSegment.INDEX,
        trading_symbol="NIFTY",
        expiry_date=date(2026, 9, 4),
    )
    acc, q = validate([idx])
    assert acc == [] and q[0].reason == "index row has an expiry_date"


def test_invalid_option_strike_lot_tick():
    assert validate([_rec(strike_price=Decimal("0"))])[1][0].reason.startswith(
        "invalid strike_price"
    )
    assert validate([_rec(strike_price=Decimal("-5"))])[1][0].reason.startswith(
        "invalid strike_price"
    )
    assert validate([_rec(lot_size=0)])[1][0].reason.startswith("invalid lot_size")
    assert validate([_rec(tick_size=Decimal("0"))])[1][0].reason.startswith("invalid tick_size")


def test_future_with_strike_is_rejected():
    fut = _rec(
        instrument_type=InstrumentType.FUTURE,
        option_type=None,
        strike_price=Decimal("100"),
        weekly=False,
    )
    assert validate([fut])[1][0].reason == "future row has a strike_price"


def test_has_intraday_oi_flag_by_type():
    fut = _rec(
        instrument_type=InstrumentType.FUTURE, option_type=None, strike_price=None, weekly=False
    )
    assert validate([fut])[0][0].has_intraday_oi is True
    assert validate([_rec()])[0][0].has_intraday_oi is True  # option


def test_duplicate_provider_key_quarantines_all_collliders():
    a = _rec(provider_symbol="NSE_FO|DUP", expiry_date=date(2026, 9, 4), weekly=True)
    b = _rec(
        provider_symbol="NSE_FO|DUP",
        expiry_date=date(2026, 9, 11),
        weekly=True,
        strike_price=Decimal("24500"),
    )
    acc, q = validate([a, b])
    assert acc == []
    assert [x.reason for x in q] == ["duplicate provider instrument key"] * 2


def test_duplicate_contract_key_quarantines_all_collliders():
    a = _rec(provider_symbol="NSE_FO|A")
    b = _rec(provider_symbol="NSE_FO|B")  # same contract_key inputs
    acc, q = validate([a, b])
    assert acc == []
    assert {x.reason for x in q} == {"duplicate canonical contract"}


def test_output_is_sorted_and_deterministic():
    records, _ = records_from_master(SAMPLE)
    a_acc, a_q = validate(records)
    b_acc, b_q = validate(list(reversed(records)))
    assert [c.contract_key for c in a_acc] == [c.contract_key for c in b_acc]
    assert [q.reason for q in a_q] == [q.reason for q in b_q]
    assert a_acc == sorted(a_acc, key=lambda c: c.sort_key())
