"""Phase 2.3 — pure candle-row normalisation (docs/09 §2.4, docs/11 PV-7)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from analytical_core.enums import Timeframe
from app.providers.upstox.normalize import (
    UpstoxCandleFormatError,
    candle_ts_to_bar_open_utc,
    normalize_candle,
    parse_iso_ts,
    session_open_utc,
)

IST = ZoneInfo("Asia/Kolkata")
SRC = "upstox:v3/historical-candle"

# a full 7-element F&O row and a 6-element (no-OI) row
FO_ROW = ["2026-08-27T09:15:00+05:30", 24000.5, 24010, 23990.25, 24005, 1000, 54321]
NO_OI_ROW = ["2026-08-27T09:15:00+05:30", 100, 100, 100, 100, 0]


def test_first_session_minute_maps_to_0345z():
    ts = candle_ts_to_bar_open_utc(FO_ROW[0], Timeframe.M1, is_bar_close=False)
    assert ts == datetime(2026, 8, 27, 3, 45, tzinfo=UTC)
    assert ts.tzinfo is UTC


def test_last_session_minute_maps_correctly():
    ts = candle_ts_to_bar_open_utc("2026-08-27T15:29:00+05:30", Timeframe.M1, is_bar_close=False)
    assert ts == datetime(2026, 8, 27, 9, 59, tzinfo=UTC)


def test_bar_close_fallback_subtracts_one_interval():
    # PV-7 fallback: a provider that returned bar-CLOSE would need -1 interval.
    ts = candle_ts_to_bar_open_utc("2026-08-27T09:16:00+05:30", Timeframe.M1, is_bar_close=True)
    assert ts == datetime(2026, 8, 27, 3, 45, tzinfo=UTC)


def test_d1_is_reanchored_to_session_open_instant():
    # provider daily candle carries a midnight-IST stamp; we anchor to 09:15 IST.
    assert candle_ts_to_bar_open_utc(
        "2026-08-27T00:00:00+05:30", Timeframe.D1, is_bar_close=False
    ) == datetime(2026, 8, 27, 3, 45, tzinfo=UTC)
    # bar_close has no effect on a daily anchor
    assert candle_ts_to_bar_open_utc(
        "2026-08-27T00:00:00+05:30", Timeframe.D1, is_bar_close=True
    ) == datetime(2026, 8, 27, 3, 45, tzinfo=UTC)


def test_session_open_utc_helper():
    assert session_open_utc(date(2026, 8, 27)) == datetime(2026, 8, 27, 3, 45, tzinfo=UTC)


def test_parse_iso_ts_requires_offset():
    assert parse_iso_ts("2026-08-27T09:15:00+05:30").utcoffset() is not None
    with pytest.raises(UpstoxCandleFormatError):
        parse_iso_ts("2026-08-27T09:15:00")  # naive — never guessed
    with pytest.raises(UpstoxCandleFormatError):
        parse_iso_ts(1690000000)  # not a string


def test_normalize_fo_row_full_fields():
    bar = normalize_candle(FO_ROW, Timeframe.M1, is_final=True, source=SRC)
    assert (bar.open, bar.high, bar.low, bar.close) == (
        Decimal("24000.5"),
        Decimal("24010"),
        Decimal("23990.25"),
        Decimal("24005"),
    )
    assert bar.volume == 1000 and isinstance(bar.volume, int)
    assert bar.open_interest == 54321
    assert bar.is_final is True and bar.source == SRC
    assert bar.ts == datetime(2026, 8, 27, 3, 45, tzinfo=UTC)


def test_normalize_six_element_row_has_no_oi():
    bar = normalize_candle(NO_OI_ROW, Timeframe.M1, is_final=True, source=SRC)
    assert bar.open_interest is None  # absent, not zero-filled


def test_normalize_seven_element_zero_oi_is_faithful_zero():
    row = [*NO_OI_ROW, 0]
    bar = normalize_candle(row, Timeframe.M1, is_final=True, source=SRC)
    assert bar.open_interest == 0  # provider said 0 -> we report 0, not None


@pytest.mark.parametrize(
    "bad",
    [
        ["2026-08-27T09:15:00+05:30", 1, 2, 3],  # too short
        "not-a-row",
        ["2026-08-27T09:15:00+05:30", "x", 2, 3, 4, 5, 6],  # non-numeric price
        ["2026-08-27T09:15:00+05:30", 1, 2, 3, 4, "v", 6],  # non-integer volume
        ["2026-08-27T09:15:00+05:30", 1, 2, 3, 4, 5, "oi"],  # non-integer OI
        ["2026-08-27T09:15:00", 1, 2, 3, 4, 5, 6],  # naive ts
    ],
)
def test_normalize_rejects_malformed_rows(bad):
    with pytest.raises(UpstoxCandleFormatError):
        normalize_candle(bad, Timeframe.M1, is_final=True, source=SRC)


def test_normalize_is_deterministic():
    a = normalize_candle(FO_ROW, Timeframe.M1, is_final=True, source=SRC)
    b = normalize_candle(list(FO_ROW), Timeframe.M1, is_final=True, source=SRC)
    assert a == b
