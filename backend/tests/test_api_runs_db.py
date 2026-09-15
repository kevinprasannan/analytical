"""Async ``POST /runs`` + Idempotency-Key + single-flight 409 (docs/07 §4.6, §3).

``TestClient`` runs FastAPI background tasks synchronously once the response is
returned, so the cycle has finished by the time ``client.post`` returns here.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from analytical_core.enums import InstrumentSegment, InstrumentType
from app.api.main import create_app
from app.config import get_settings
from app.db import models as md

pytestmark = pytest.mark.db


@pytest.fixture()
def client(migrated_engine, db_url, monkeypatch):
    monkeypatch.setenv("ANALYTICAL_DATABASE_URL", db_url)
    monkeypatch.setenv("ANALYTICAL_ACTIVE_PROVIDER", "stub")
    get_settings.cache_clear()
    from app.db.session import reset_engine

    reset_engine()
    with Session(migrated_engine) as seed:
        inst = md.Instrument(
            contract_key="NIFTY-FUT-2026-09",
            symbol="NIFTY",
            segment=InstrumentSegment.FUT,
            instrument_type=InstrumentType.FUTURE,
            is_tracked=True,
        )
        seed.add(inst)
        seed.flush()
        seed.add(
            md.ProviderInstrumentMap(
                instrument_id=inst.id, provider="stub", provider_symbol="STUB:NIFTY", is_active=True
            )
        )
        seed.commit()
    yield TestClient(create_app())
    get_settings.cache_clear()
    reset_engine()


def test_post_runs_is_async_202_then_cycle_completes(client, migrated_engine):
    r = client.post("/api/v1/runs", json={"trigger": "MANUAL"})
    assert r.status_code == 202
    body = r.json()
    run_id = body["id"]
    assert r.headers["location"] == f"/api/v1/runs/{run_id}"

    # background task already ran under TestClient
    detail = client.get(f"/api/v1/runs/{run_id}").json()
    assert detail["status"] in {"SUCCEEDED", "PARTIAL"}
    assert {p["phase"] for p in detail["phase_status"]} == {"INGEST", "ANALYZE", "SCORE"}

    with Session(migrated_engine) as s:
        assert s.execute(select(func.count()).select_from(md.AnalysisRun)).scalar_one() == 1


def test_idempotency_key_replays_the_same_run(client, migrated_engine):
    h = {"Idempotency-Key": "abc-123"}
    first = client.post("/api/v1/runs", json={"trigger": "MANUAL"}, headers=h)
    assert first.status_code == 202
    rid = first.json()["id"]

    second = client.post("/api/v1/runs", json={"trigger": "MANUAL"}, headers=h)
    assert second.status_code == 200
    assert second.json()["id"] == rid
    assert second.headers["location"] == f"/api/v1/runs/{rid}"

    with Session(migrated_engine) as s:
        assert s.execute(select(func.count()).select_from(md.AnalysisRun)).scalar_one() == 1
        row = s.get(md.AnalysisRun, rid)
        assert row.config_snapshot["idempotency_key"] == "abc-123"

    # a different key starts a new cycle
    third = client.post(
        "/api/v1/runs", json={"trigger": "MANUAL"}, headers={"Idempotency-Key": "z"}
    )
    assert third.status_code == 202
    assert third.json()["id"] != rid


def test_conflict_409_when_a_cycle_holds_the_lock(client, db_url):
    from app.worker.deps import CYCLE_ADVISORY_LOCK_KEY

    holder_engine = create_engine(db_url, future=True)
    holder = holder_engine.connect()
    assert holder.execute(select(func.pg_try_advisory_lock(CYCLE_ADVISORY_LOCK_KEY))).scalar_one()
    try:
        r = client.post("/api/v1/runs", json={"trigger": "MANUAL"})
        assert r.status_code == 409
        assert r.headers.get("retry-after") == "30"
    finally:
        holder.execute(select(func.pg_advisory_unlock(CYCLE_ADVISORY_LOCK_KEY)))
        holder.close()
        holder_engine.dispose()


def test_meta_versions_stale_counts_zero_after_a_fresh_cycle(client):
    client.post("/api/v1/runs", json={"trigger": "MANUAL"})
    body = client.get("/api/v1/meta/versions").json()
    assert body["stale_results"] is False
    assert body["stale_result_counts"] == {"analysis_results": 0, "signal_scores": 0}
