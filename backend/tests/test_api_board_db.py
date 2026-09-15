"""``GET /api/v1/board`` (docs/07 §4.11) — the data-first market board."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.main import create_app

pytestmark = pytest.mark.db
IST = timezone(timedelta(hours=5, minutes=30))


@pytest.fixture()
def client(migrated_engine):
    with Session(migrated_engine) as s:
        s.execute(
            text(
                "INSERT INTO instruments (id,contract_key,symbol,segment,instrument_type,"
                "is_active,is_tracked) VALUES "
                "(1,'NIFTY-INDEX','NIFTY','INDEX','INDEX',true,true),"
                "(2,'NIFTY-FUT-2026-09','NIFTY FUT','FUT','FUTURE',true,true),"
                "(3,'NIFTY-OPT-2026-09-24000-CE','NIFTY','OPT','OPTION',true,true),"
                "(4,'BANKNIFTY-INDEX','BANKNIFTY','INDEX','INDEX',true,false)"  # not tracked
            )
        )
        # D1: yesterday + today for the index
        for iid, base in ((1, 24000.0), (2, 24050.0)):
            s.execute(
                text(
                    "INSERT INTO ohlcv_bars (instrument_id,timeframe,ts,open,high,low,close,"
                    "volume,provider,is_final) VALUES (:i,'D1',:t1,:o,:o,:o,:pc,0,'upstox',true),"
                    "(:i,'D1',:t2,:o2,:hi,:lo,:c,0,'upstox',false)"
                ),
                {
                    "i": iid,
                    "t1": datetime(2026, 8, 28, 3, 45, tzinfo=UTC),
                    "t2": datetime(2026, 8, 31, 3, 45, tzinfo=UTC),
                    "o": base,
                    "pc": base,
                    "o2": base + 10,
                    "hi": base + 120,
                    "lo": base - 30,
                    "c": base + 60,
                },
            )
            # a fresher M1
            s.execute(
                text(
                    "INSERT INTO ohlcv_bars (instrument_id,timeframe,ts,open,high,low,close,"
                    "volume,provider,is_final) VALUES (:i,'M1',:t,:c,:c,:c,:c,0,'upstox',false)"
                ),
                {"i": iid, "t": datetime(2026, 8, 31, 9, 59, tzinfo=UTC), "c": base + 75},
            )
        s.execute(
            text(
                "INSERT INTO open_interest (instrument_id,timeframe,ts,oi,provider,is_final) "
                "VALUES (2,'M1',:t,987654,'upstox',false)"
            ),
            {"t": datetime(2026, 8, 31, 9, 59, tzinfo=UTC)},
        )
        s.commit()
    app = create_app()

    def _override():
        s = Session(migrated_engine)
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override
    yield TestClient(app)


def test_board_lists_only_tracked_index_and_future(client):
    rows = client.get("/api/v1/board").json()["rows"]
    keys = {r["contract_key"] for r in rows}
    assert keys == {"NIFTY-INDEX", "NIFTY-FUT-2026-09"}  # option + untracked index excluded


def test_board_row_fields(client):
    rows = {r["contract_key"]: r for r in client.get("/api/v1/board").json()["rows"]}
    idx = rows["NIFTY-INDEX"]
    assert idx["last_price"] == pytest.approx(24075.0)  # newest M1
    assert idx["prev_close"] == pytest.approx(24000.0)  # yesterday D1 close
    # (24075 - 24000) / 24000 * 100
    assert idx["day_change_pct"] == pytest.approx(0.3125, abs=1e-3)
    # (24120 - 23970) / 24000 * 100
    assert idx["day_range_pct"] == pytest.approx(0.625, abs=1e-3)
    assert idx["oi"] is None  # index has none

    fut = rows["NIFTY-FUT-2026-09"]
    assert fut["oi"] == 987654
    assert fut["instrument_type"] == "FUTURE"


def test_board_reports_history_coverage(client):
    idx = {r["contract_key"]: r for r in client.get("/api/v1/board").json()["rows"]}["NIFTY-INDEX"]
    assert idx["d1_from"] == "2026-08-28"
    assert idx["d1_through"] == "2026-08-31"
    assert idx["d1_bars"] == 2
    assert idx["m1_from"] == idx["m1_through"] == "2026-08-31"
    # D1 through 2026-08-31 — "current" depends on the wall clock, but the flag is a bool
    assert isinstance(idx["history_ok"], bool)
