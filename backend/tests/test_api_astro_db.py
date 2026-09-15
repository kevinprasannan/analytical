"""``GET /api/v1/astro/study`` (docs/07 §4.9) — end to end on PostgreSQL."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.main import create_app
from app.astro import backfill as bf

pytestmark = pytest.mark.db
IST = timezone(timedelta(hours=5, minutes=30))


@pytest.fixture()
def client(migrated_engine):
    with Session(migrated_engine) as seed:
        seed.execute(
            text(
                "INSERT INTO instruments (id,contract_key,symbol,segment,instrument_type,"
                "is_active,is_tracked) VALUES (1,'NIFTY-INDEX','NIFTY','INDEX','INDEX',true,true)"
            )
        )
        d = date(2024, 1, 1)
        close = 100.0
        for i in range(24):
            if d.weekday() < 5:
                ts = datetime(d.year, d.month, d.day, tzinfo=IST) + timedelta(hours=3, minutes=45)
                close *= 1.0 + (0.004 if i % 3 else -0.006)
                seed.execute(
                    text(
                        "INSERT INTO ohlcv_bars (instrument_id,timeframe,ts,open,high,low,close,"
                        "volume,provider,is_final) VALUES "
                        "(1,'D1',:ts,:o,:h,:l,:c,0,'test',true)"
                    ),
                    {"ts": ts, "o": close, "h": close * 1.01, "l": close * 0.99, "c": close},
                )
            d += timedelta(days=1)
        seed.commit()
        bf.build(
            seed,
            start=date(2024, 1, 1),
            end=date(2024, 1, 26),
            latitude=19.076090,
            longitude=72.877426,
            with_shadbala=False,
        )

    app = create_app()

    def _override():
        s = Session(migrated_engine)
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override
    yield TestClient(app)


def test_astro_study_ok(client):
    r = client.get("/api/v1/astro/study")
    assert r.status_code == 200
    body = r.json()
    assert body["underlying"] == "NIFTY-INDEX"
    assert body["n_days"] >= 1
    assert set(body) >= {
        "baseline",
        "by_weekday",
        "by_moon_nakshatra",
        "by_lagna_rashi",
        "by_tithi",
        "by_paksha",
    }
    assert body["baseline"]["n"] == body["n_days"]
    assert sum(b["n"] for b in body["by_weekday"]) == body["n_days"]
    for b in body["by_weekday"]:
        assert b["key"] in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
        assert -100 <= b["pct_up"] <= 100


def test_astro_study_unknown_underlying_is_404(client):
    r = client.get("/api/v1/astro/study", params={"underlying": "NOPE-INDEX"})
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")


def test_astro_study_date_window(client):
    full = client.get("/api/v1/astro/study").json()
    windowed = client.get("/api/v1/astro/study", params={"start": "2024-01-10"}).json()
    assert windowed["n_days"] <= full["n_days"]
    assert windowed["first"] >= "2024-01-10"
