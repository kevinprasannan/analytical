"""``POST /instruments`` + ``DELETE /instruments/{id}`` (docs/07 §4.2) — PG."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.main import create_app
from app.config import get_settings

pytestmark = pytest.mark.db


@pytest.fixture()
def client(migrated_engine, monkeypatch):
    monkeypatch.setenv("ANALYTICAL_ACTIVE_PROVIDER", "stub")
    get_settings.cache_clear()
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


def test_create_index_then_future_under_it(client):
    r = client.post(
        "/api/v1/instruments",
        json={
            "instrument_type": "INDEX",
            "segment": "INDEX",
            "provider_symbol": "NSE_INDEX|Nifty 50",
            "symbol": "NIFTY",
        },
    )
    assert r.status_code == 201, r.text
    idx = r.json()
    assert idx["contract_key"] == "NIFTY-INDEX"
    assert idx["provider"] == "stub"

    r = client.post(
        "/api/v1/instruments",
        json={
            "instrument_type": "FUTURE",
            "segment": "FUT",
            "provider_symbol": "NSE_FO|68407",
            "underlying_contract_key": "NIFTY-INDEX",
            "expiry_date": "2026-09-29",
            "expiry_kind": "MONTHLY",
        },
    )
    assert r.status_code == 201, r.text
    fut = r.json()
    assert fut["contract_key"] == "NIFTY-FUT-2026-09"

    detail = client.get(f"/api/v1/instruments/{fut['instrument_id']}").json()
    assert detail["underlying_id"] == idx["instrument_id"]
    assert detail["is_tracked"] is True
    assert detail["has_intraday_oi"] is True


def test_create_rejects_duplicate_contract_key(client):
    body = {
        "instrument_type": "INDEX",
        "segment": "INDEX",
        "provider_symbol": "NSE_INDEX|Nifty Bank",
        "symbol": "BANKNIFTY",
    }
    assert client.post("/api/v1/instruments", json=body).status_code == 201
    dup = client.post(
        "/api/v1/instruments", json={**body, "provider_symbol": "NSE_INDEX|Nifty Bank X"}
    )
    assert dup.status_code == 409


def test_delete_removes_instrument_and_children(client, migrated_engine):
    iid = client.post(
        "/api/v1/instruments",
        json={
            "instrument_type": "INDEX",
            "segment": "INDEX",
            "provider_symbol": "NSE_INDEX|X",
            "symbol": "X",
        },
    ).json()["instrument_id"]
    with Session(migrated_engine) as s:
        s.execute(
            text(
                "INSERT INTO ohlcv_bars (instrument_id,timeframe,ts,open,high,low,close,"
                "volume,provider,is_final) VALUES (:i,'M1',:t,1,1,1,1,0,'stub',true)"
            ),
            {"i": iid, "t": datetime(2026, 8, 31, 4, 0, tzinfo=UTC)},
        )
        s.commit()

    r = client.delete(f"/api/v1/instruments/{iid}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["contract_key"] == "X-INDEX"
    assert body["children"].get("ohlcv_bars") == 1
    assert body["children"].get("provider_instrument_map") == 1
    assert client.get(f"/api/v1/instruments/{iid}").status_code == 404


def test_delete_underlying_blocked_then_forced(client):
    idx = client.post(
        "/api/v1/instruments",
        json={
            "instrument_type": "INDEX",
            "segment": "INDEX",
            "provider_symbol": "NSE_INDEX|U",
            "symbol": "U",
        },
    ).json()
    client.post(
        "/api/v1/instruments",
        json={
            "instrument_type": "FUTURE",
            "segment": "FUT",
            "provider_symbol": "NSE_FO|U1",
            "underlying_contract_key": "U-INDEX",
            "expiry_date": "2026-10-27",
            "expiry_kind": "MONTHLY",
        },
    )
    assert client.delete(f"/api/v1/instruments/{idx['instrument_id']}").status_code == 409
    forced = client.delete(f"/api/v1/instruments/{idx['instrument_id']}?force=true")
    assert forced.status_code == 200
    assert forced.json()["children"].get("instruments") == 1  # the dependent future


def test_delete_unknown_is_404(client):
    assert client.delete("/api/v1/instruments/999999").status_code == 404
