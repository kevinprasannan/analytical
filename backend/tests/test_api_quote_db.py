"""``GET /api/v1/instruments/{id}/quote`` (docs/07 §4.10) — end to end on PG
against the deterministic stub provider."""

from __future__ import annotations

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
    with Session(migrated_engine) as s:
        s.execute(
            text(
                "INSERT INTO instruments (id,contract_key,symbol,segment,instrument_type,"
                "is_active,is_tracked) VALUES "
                "(1,'NIFTY-INDEX','NIFTY','INDEX','INDEX',true,true),"
                "(2,'NIFTY-24000-CE','NIFTY','OPT','OPTION',true,true)"
            )
        )
        s.execute(
            text(
                "INSERT INTO provider_instrument_map (instrument_id,provider,provider_symbol,is_active)"
                " VALUES (1,'stub','STUB|NIFTY',true),(2,'stub','STUB|NIFTY-24000-CE',true)"
            )
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
    get_settings.cache_clear()


def test_index_quote_has_price_and_no_greeks(client):
    r = client.get("/api/v1/instruments/1/quote")
    assert r.status_code == 200
    b = r.json()
    assert b["provider"] == "stub" and b["provider_symbol"] == "STUB|NIFTY"
    assert b["last_price"] is not None and b["open"] is not None
    assert b["greeks"] is None


def test_option_quote_includes_greeks(client):
    b = client.get("/api/v1/instruments/2/quote").json()
    assert b["greeks"] is not None
    assert b["greeks"]["iv"] == pytest.approx(0.15)
    assert b["greeks"]["delta"] == pytest.approx(0.5)
    assert b["oi"] is not None  # option full quote carries OI


def test_unknown_instrument_is_404(client):
    assert client.get("/api/v1/instruments/999/quote").status_code == 404


def test_instrument_without_active_map_is_404(client, migrated_engine):
    with Session(migrated_engine) as s:
        s.execute(
            text(
                "INSERT INTO instruments (id,contract_key,symbol,segment,instrument_type,"
                "is_active,is_tracked) VALUES (3,'ORPHAN','O','INDEX','INDEX',true,true)"
            )
        )
        s.commit()
    assert client.get("/api/v1/instruments/3/quote").status_code == 404
