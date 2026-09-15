"""Phase 2.2 — Upstox instrument-master parsing + normalisation (§2, §11)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from analytical_core.enums import InstrumentSegment, InstrumentType, OptionType
from app.providers.upstox.instrument_master import (
    InstrumentMasterFormatError,
    normalise,
    read_master,
    records_from_master,
)
from tests.conftest import UPSTOX_MASTER_DIR

SAMPLE = UPSTOX_MASTER_DIR / "nse_master_sample.json"
SAMPLE_GZ = UPSTOX_MASTER_DIR / "nse_master_sample.json.gz"
BAD_ROWS = UPSTOX_MASTER_DIR / "nse_master_bad_rows.json"


def _by_key(records):
    return {r.provider_symbol: r for r in records}


def test_read_json_and_gz_agree():
    assert read_master(SAMPLE) == read_master(SAMPLE_GZ)


def test_read_rejects_non_list(tmp_path):
    p = tmp_path / "m.json"
    p.write_text('{"not": "a list"}', encoding="utf-8")
    with pytest.raises(InstrumentMasterFormatError):
        read_master(p)


def test_read_missing_file():
    with pytest.raises(InstrumentMasterFormatError):
        read_master(UPSTOX_MASTER_DIR / "does_not_exist.json")


def test_normalise_maps_index_row():
    records, rejected = records_from_master(SAMPLE)
    assert rejected == []
    nifty = _by_key(records)["NSE_INDEX|Nifty 50"]
    assert nifty.instrument_type is InstrumentType.INDEX
    assert nifty.segment is InstrumentSegment.INDEX
    assert nifty.trading_symbol == "NIFTY"
    assert nifty.expiry_date is None
    assert nifty.strike_price is None
    assert nifty.weekly is None
    assert nifty.provider == "upstox"
    assert nifty.raw["instrument_key"] == "NSE_INDEX|Nifty 50"  # provenance preserved


def test_normalise_maps_future_row():
    records, _ = records_from_master(SAMPLE)
    fut = _by_key(records)["NSE_FO|68407"]
    assert fut.instrument_type is InstrumentType.FUTURE
    assert fut.segment is InstrumentSegment.FUT
    assert fut.expiry_date == date(2026, 9, 24)  # epoch-ms -> IST date
    assert fut.strike_price is None  # provider 0.0 normalised to None
    assert fut.weekly is False
    assert fut.lot_size == 65
    assert fut.tick_size == Decimal("10.0")
    assert fut.underlying_symbol == "NIFTY"
    assert fut.underlying_provider_key == "NSE_INDEX|Nifty 50"


def test_normalise_maps_option_rows():
    records, _ = records_from_master(SAMPLE)
    ce = _by_key(records)["NSE_FO|46913"]
    assert ce.instrument_type is InstrumentType.OPTION
    assert ce.segment is InstrumentSegment.OPT
    assert ce.option_type is OptionType.CE
    assert ce.strike_price == Decimal("24000.0")
    assert ce.weekly is True
    pe = _by_key(records)["NSE_FO|46914"]
    assert pe.option_type is OptionType.PE


def test_normalise_rejects_unhandled_kinds():
    records, rejected = records_from_master(BAD_ROWS)
    reasons = {r.reason for r in rejected}
    assert "unsupported segment 'NSE_EQ'" in reasons
    assert "unsupported segment 'NSE_COM'" in reasons
    assert "unsupported instrument_type 'SG'" in reasons
    assert "missing instrument_key" in reasons
    assert any("malformed expiry" in r for r in reasons)
    # the shaped-but-invalid rows still make it through normalisation
    assert {r.provider_symbol for r in records} >= {"NSE_FO|99002", "NSE_FO|99003", "NSE_FO|DUP"}


def test_normalise_is_deterministic():
    a = normalise(read_master(SAMPLE))
    b = normalise(read_master(SAMPLE))
    assert [r.provider_symbol for r in a[0]] == [r.provider_symbol for r in b[0]]
    assert [r.reason for r in a[1]] == [r.reason for r in b[1]]
