"""``services.daily_digest`` (docs/07 §4.12) — end to end on PostgreSQL:
seeded D1 bars + one TPO market-profile session, then the digest on read."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import services

pytestmark = pytest.mark.db
IST = timezone(timedelta(hours=5, minutes=30))


@pytest.fixture()
def session(migrated_engine):
    with Session(migrated_engine) as s:
        yield s


def _seed(session: Session) -> None:
    session.execute(
        text(
            "INSERT INTO instruments (id,contract_key,symbol,segment,instrument_type,"
            "is_active,is_tracked) VALUES (1,'NIFTY-INDEX','NIFTY','INDEX','INDEX',true,true)"
        )
    )
    # day 1 close 100, day 2 breaks above (h 108 > pdh 105), day 3 breaks below
    bars = [
        # d, o, h, l, c
        (date(2026, 8, 24), 99, 105, 97, 100),
        (date(2026, 8, 25), 101, 108, 100, 107),  # PDH_BREAK, close > PDH
        (date(2026, 8, 26), 106, 107, 95, 96),  # PDL_BREAK, close < PDL
    ]
    for d, o, h, lo, c in bars:
        ts = datetime(d.year, d.month, d.day, tzinfo=IST) + timedelta(hours=3, minutes=45)
        session.execute(
            text(
                "INSERT INTO ohlcv_bars (instrument_id,timeframe,ts,open,high,low,close,"
                "volume,provider,is_final) VALUES (1,'D1',:ts,:o,:h,:l,:c,0,'upstox',true)"
            ),
            {"ts": ts, "o": o, "h": h, "l": lo, "c": c},
        )
    session.execute(
        text(
            "INSERT INTO market_profile_sessions (instrument_id,session_date,profile_type,"
            "bin_size,poc,vah,val,session_high,session_low,profile_shape,is_session_complete,"
            "close,bins,events,mp_events_version,algo_version,params_hash) VALUES "
            "(1,'2026-08-25','TPO',1,104,106,102,108,100,'NORMAL',true,107,'{}'::jsonb,"
            "'{\"day_type\": {\"day_type\": \"TREND_UP\"}}'::jsonb,'0.1.0','x','h')"
        )
    )
    session.commit()


def test_daily_digest_ohlc_pdh_pdl_and_profile(session):
    _seed(session)
    res = services.daily_digest(session, 1, sort="d")
    assert res is not None
    items = {r["d"]: r for r in res["items"]}
    # day 1 has no prev row -> excluded
    assert set(items) == {"2026-08-25", "2026-08-26"}

    up = items["2026-08-25"]
    assert up["pdh"] == 105.0 and up["pdl"] == 97.0
    assert up["pdh_broken"] is True and up["pdl_broken"] is False
    assert up["pdh_close_above"] is True
    assert up["range_type"] == "PDH_BREAK"
    assert up["profile_shape"] == "NORMAL" and up["day_type"] == "TREND_UP"
    assert up["poc"] == 104.0 and up["close_vs_value"] == "ABOVE"  # close 107 > vah 106

    dn = items["2026-08-26"]
    assert dn["pdl_broken"] is True and dn["pdh_broken"] is False
    assert dn["pdl_close_below"] is True and dn["range_type"] == "PDL_BREAK"
    assert dn["profile_shape"] is None  # no MP row for this day

    # D1 day-type classified for every row (no trailing history here → no ratio gate)
    for r in res["items"]:
        assert r["d1_day_type"] in {
            "TREND_UP",
            "TREND_DOWN",
            "NEUTRAL",
            "NEUTRAL_EXTREME",
            "NORMAL",
            "NORMAL_VARIATION",
            "RANGE",
            "LARGE_RANGE",
            "UNDETERMINED",
        }
        assert 0.0 <= r["close_range_pos"] <= 1.0
    # day 2 closed on its high (c 107 == h 108? no, h 108) -> close_pos = (107-100)/8
    assert abs(up["close_range_pos"] - (107 - 100) / (108 - 100)) < 1e-6

    s = res["summary"]
    assert s["days"] == 2 and s["pdh_breaks"] == 1 and s["pdl_breaks"] == 1
    assert s["days_with_profile"] == 1
    assert sum(s["d1_day_type_counts"].values()) == 2


def _seed_gap_fade(session: Session) -> None:
    session.execute(
        text(
            "INSERT INTO instruments (id,contract_key,symbol,segment,instrument_type,"
            "is_active,is_tracked) VALUES (2,'BANKNIFTY-INDEX','BANKNIFTY','INDEX','INDEX',true,true)"
        )
    )
    bars = [
        # d, o, h, l, c — prev_close chains day to day
        (date(2026, 8, 24), 100.0, 101.0, 99.0, 100.0),  # anchor, no prev row -> excluded
        (date(2026, 8, 25), 101.0, 102.0, 99.3, 99.4),  # gap +1.0%, close -0.6% -> a "gap fade"
        (date(2026, 8, 26), 99.5, 100.0, 99.0, 99.6),  # gap +0.1%, close +0.2% -> no match
        (date(2026, 8, 27), 99.0, 99.2, 96.0, 96.5),  # gap -0.6%, close -3.1% -> gap down, not up
    ]
    for d, o, h, lo, c in bars:
        ts = datetime(d.year, d.month, d.day, tzinfo=IST) + timedelta(hours=3, minutes=45)
        session.execute(
            text(
                "INSERT INTO ohlcv_bars (instrument_id,timeframe,ts,open,high,low,close,"
                "volume,provider,is_final) VALUES (2,'D1',:ts,:o,:h,:l,:c,0,'upstox',true)"
            ),
            {"ts": ts, "o": o, "h": h, "l": lo, "c": c},
        )
    session.commit()


def test_daily_digest_gap_up_then_close_down_filter(session):
    # owner: "open gapup like more than .5 % and close -.5% the days"
    _seed_gap_fade(session)
    res = services.daily_digest(session, 2, sort="d", gap_min_pct=0.5, chg_max_pct=-0.5)
    assert res is not None
    days = {r["d"] for r in res["items"]}
    assert days == {"2026-08-25"}
    row = res["items"][0]
    assert row["gap_pct"] == pytest.approx(1.0, abs=1e-3)
    assert row["change_pct"] == pytest.approx(-0.6, abs=1e-3)
    assert res["gap_min_pct"] == 0.5 and res["chg_max_pct"] == -0.5
    assert res["gap_max_pct"] is None and res["chg_min_pct"] is None
    # summary reflects only the matching (filtered) rows, not the full history
    assert res["summary"]["days"] == 1
    assert res["total"] == 1


def test_daily_digest_gap_filter_excludes_gap_down_days(session):
    _seed_gap_fade(session)
    res = services.daily_digest(session, 2, gap_min_pct=0.5)
    days = {r["d"] for r in res["items"]}
    assert "2026-08-27" not in days  # gapped down, not up
    assert days == {"2026-08-25"}


def test_daily_digest_unknown_instrument_is_none(session):
    assert services.daily_digest(session, 999) is None


def test_daily_digest_bad_sort_raises(session):
    _seed(session)
    with pytest.raises(ValueError):
        services.daily_digest(session, 1, sort="banana")
