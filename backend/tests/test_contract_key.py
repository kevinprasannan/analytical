"""Phase 2.2 — ``contract_key`` (platform-stable canonical identity, §3)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from analytical_core.enums import ExpiryKind, InstrumentType, OptionType
from app.instruments.contract_key import (
    ContractKeyError,
    build_contract_key,
    parse_contract_key,
)


def test_index_key():
    assert (
        build_contract_key(instrument_type=InstrumentType.INDEX, underlying_symbol="NIFTY")
        == "NIFTY-INDEX"
    )
    assert (
        build_contract_key(instrument_type=InstrumentType.INDEX, underlying_symbol="Nifty Bank")
        == "NIFTYBANK-INDEX"
    )


def test_future_monthly_uses_year_month_only():
    a = build_contract_key(
        instrument_type=InstrumentType.FUTURE,
        underlying_symbol="NIFTY",
        expiry_date=date(2026, 9, 24),
        expiry_kind=ExpiryKind.MONTHLY,
    )
    b = build_contract_key(
        instrument_type=InstrumentType.FUTURE,
        underlying_symbol="NIFTY",
        expiry_date=date(2026, 9, 29),  # holiday-shifted expiry, same month
        expiry_kind=ExpiryKind.MONTHLY,
    )
    assert a == b == "NIFTY-FUT-2026-09"


def test_future_weekly_uses_full_date():
    assert (
        build_contract_key(
            instrument_type=InstrumentType.FUTURE,
            underlying_symbol="NIFTY",
            expiry_date=date(2026, 9, 4),
            expiry_kind=ExpiryKind.WEEKLY,
        )
        == "NIFTY-FUT-2026-09-04"
    )


def test_option_keys():
    monthly = build_contract_key(
        instrument_type=InstrumentType.OPTION,
        underlying_symbol="BANKNIFTY",
        expiry_date=date(2026, 9, 24),
        expiry_kind=ExpiryKind.MONTHLY,
        strike_price=Decimal("54000"),
        option_type=OptionType.CE,
    )
    assert monthly == "BANKNIFTY-OPT-2026-09-54000-CE"
    weekly = build_contract_key(
        instrument_type=InstrumentType.OPTION,
        underlying_symbol="NIFTY",
        expiry_date=date(2026, 9, 4),
        expiry_kind=ExpiryKind.WEEKLY,
        strike_price=Decimal("24000.0000"),
        option_type=OptionType.PE,
    )
    assert weekly == "NIFTY-OPT-2026-09-04-24000-PE"


def test_option_fractional_strike():
    assert (
        build_contract_key(
            instrument_type=InstrumentType.OPTION,
            underlying_symbol="X",
            expiry_date=date(2026, 9, 4),
            expiry_kind=ExpiryKind.WEEKLY,
            strike_price=Decimal("24000.50"),
            option_type=OptionType.CE,
        )
        == "X-OPT-2026-09-04-24000.5-CE"
    )


def test_deterministic():
    kw = dict(
        instrument_type=InstrumentType.OPTION,
        underlying_symbol="NIFTY",
        expiry_date=date(2026, 9, 4),
        expiry_kind=ExpiryKind.WEEKLY,
        strike_price=Decimal("24000"),
        option_type=OptionType.CE,
    )
    assert build_contract_key(**kw) == build_contract_key(**kw)


@pytest.mark.parametrize(
    "ck",
    [
        "NIFTY-INDEX",
        "NIFTY-FUT-2026-09",
        "NIFTY-FUT-2026-09-04",
        "BANKNIFTY-OPT-2026-09-54000-CE",
        "NIFTY-OPT-2026-09-04-24000-PE",
    ],
)
def test_parse_round_trips(ck):
    parts = parse_contract_key(ck)
    assert parts.underlying == ck.split("-")[0]


def test_errors():
    with pytest.raises(ContractKeyError):
        build_contract_key(instrument_type=InstrumentType.INDEX, underlying_symbol="  ")
    with pytest.raises(ContractKeyError):
        build_contract_key(
            instrument_type=InstrumentType.FUTURE, underlying_symbol="NIFTY"
        )  # no expiry
    with pytest.raises(ContractKeyError):
        build_contract_key(
            instrument_type=InstrumentType.OPTION,
            underlying_symbol="NIFTY",
            expiry_date=date(2026, 9, 4),
            expiry_kind=ExpiryKind.WEEKLY,
            strike_price=Decimal("0"),
            option_type=OptionType.CE,
        )
    with pytest.raises(ContractKeyError):
        parse_contract_key("garbage")
