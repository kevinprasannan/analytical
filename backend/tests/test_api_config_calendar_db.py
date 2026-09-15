"""Config + calendar + /health/ready endpoints over PostgreSQL (``@pytest.mark.db``)."""

from __future__ import annotations

from datetime import date, time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.main import create_app
from app.config import get_settings
from app.db import models as md

pytestmark = pytest.mark.db


@pytest.fixture()
def client(migrated_engine, monkeypatch):
    monkeypatch.setenv("ANALYTICAL_ACTIVE_PROVIDER", "stub")
    get_settings.cache_clear()
    with Session(migrated_engine) as seed:
        for d, trading in [
            (date(2026, 8, 27), True),  # Thu
            (date(2026, 8, 28), True),  # Fri
            (date(2026, 8, 29), False),  # Sat
            (date(2026, 8, 30), False),  # Sun
            (date(2026, 8, 31), True),  # Mon
        ]:
            seed.add(
                md.MarketCalendar(
                    exchange="NSE",
                    segment="FO",
                    calendar_date=d,
                    is_trading_day=trading,
                    session_open_ist=time(9, 15),
                    session_close_ist=time(15, 30),
                    session_type="NORMAL",
                )
            )
        seed.commit()

    app = create_app()

    def _override():
        s = Session(migrated_engine)
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override
    yield TestClient(app)
    get_settings.cache_clear()


# ======================================================================================
# config
# ======================================================================================


def test_get_config_returns_effective_and_sections(client):
    body = client.get("/api/v1/config").json()
    assert body["effective"]["cycle_interval_seconds"] == 180
    assert body["sections"]["scoring"]["min_confidence"] == 0.35
    assert len(body["config_params_hash"]) == 16


def test_patch_config_persists_and_changes_hash(client):
    before = client.get("/api/v1/config").json()["config_params_hash"]
    r = client.patch("/api/v1/config", json={"scoring.min_confidence": 0.5})
    assert r.status_code == 200
    body = r.json()
    assert body["updated"] == ["scoring.min_confidence"]
    assert "next cycle" in body["effective_from"]
    assert body["config_params_hash"] != before

    after = client.get("/api/v1/config").json()
    assert after["effective"]["scoring.min_confidence"] == 0.5
    assert after["sections"]["scoring"]["min_confidence"] == 0.5


def test_patch_config_invalid_is_422_problem_json(client):
    r = client.patch("/api/v1/config", json={"scoring.min_confidence": 9})
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")

    r2 = client.patch("/api/v1/config", json={"bogus.key": 1})
    assert r2.status_code == 422


def test_config_schema_endpoint(client):
    sch = client.get("/api/v1/config/schema").json()
    assert sch["type"] == "object"
    assert "market_profile.tpo_minutes" in sch["properties"]


# ======================================================================================
# calendar
# ======================================================================================


def test_calendar_range(client):
    body = client.get("/api/v1/calendar?start=2026-08-27&end=2026-08-31").json()
    days = body["days"]
    assert [d["calendar_date"] for d in days] == [
        "2026-08-27",
        "2026-08-28",
        "2026-08-29",
        "2026-08-30",
        "2026-08-31",
    ]
    assert days[0]["is_trading_day"] is True and days[2]["is_trading_day"] is False
    assert days[0]["session_open_ist"] == "09:15"


def test_calendar_range_too_wide_is_422(client):
    r = client.get("/api/v1/calendar?start=2026-01-01&end=2028-01-01")
    assert r.status_code == 422


def test_calendar_status_open_during_session(client):
    r = client.get("/api/v1/calendar/status?now=2026-08-27T06:00:00Z")  # 11:30 IST, Thu
    body = r.json()
    assert body["is_open"] is True
    assert body["next_close"]["ist"].startswith("2026-08-27T15:30")
    assert body["seeded_until"] == "2026-08-31"


def test_calendar_status_before_open_and_weekend(client):
    pre = client.get("/api/v1/calendar/status?now=2026-08-27T02:00:00Z").json()  # 07:30 IST
    assert pre["is_open"] is False
    assert pre["next_open"]["ist"].startswith("2026-08-27T09:15")

    sat = client.get("/api/v1/calendar/status?now=2026-08-29T06:00:00Z").json()
    assert sat["is_open"] is False
    assert sat["next_open"]["ist"].startswith("2026-08-31T09:15")  # Monday


# ======================================================================================
# health/ready
# ======================================================================================


def test_health_ready_telemetry(client):
    body = client.get("/api/v1/health/ready").json()
    assert body["db_ok"] is True
    assert body["worker_running"] is False  # no cycle holding the advisory lock
    assert body["calendar_seeded_until"] == "2026-08-31"
    assert "last_cycle_seq" in body and "cycle_overrun" in body
    assert body["active_provider"] == "stub"
    # streaming telemetry (docs/02 §3.4)
    assert body["stream_enabled"] is False
    assert body["stream_in_process"] is False
    assert "recent_m1_bar_age_seconds" in body
