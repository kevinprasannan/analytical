"""``GET /instruments/catalog`` — provider-symbol autosuggest (docs/07 §4.2)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.main import create_app
from app.config import get_settings

pytestmark = pytest.mark.db

# expiry: 2026-09-29T00:00:00Z in epoch ms
_SEP_EXPIRY_MS = 1_790_640_000_000

_MASTER = [
    {
        "instrument_key": "NSE_INDEX|Nifty 50",
        "name": "Nifty 50",
        "trading_symbol": "NIFTY 50",
        "instrument_type": "INDEX",
        "segment": "NSE_INDEX",
        "exchange": "NSE",
    },
    {
        "instrument_key": "NSE_FO|68407",
        "name": "NIFTY FUT 25 SEP",
        "trading_symbol": "NIFTY FUT",
        "instrument_type": "FUT",
        "segment": "NSE_FO",
        "exchange": "NSE",
        "underlying_symbol": "NIFTY",
        "expiry": _SEP_EXPIRY_MS,
        "weekly": False,
    },
    {
        "instrument_key": "NSE_FO|45123",
        "name": "NIFTY 24000 CE 25 SEP",
        "trading_symbol": "NIFTY 24000 CE",
        "instrument_type": "CE",
        "segment": "NSE_FO",
        "exchange": "NSE",
        "underlying_symbol": "NIFTY",
        "expiry": _SEP_EXPIRY_MS,
        "weekly": True,
        "strike_price": 24000,
    },
]


@pytest.fixture()
def master_dir(tmp_path):
    d = tmp_path / "upstox"
    d.mkdir()
    (d / "NSE.json").write_text(json.dumps(_MASTER))
    return d


@pytest.fixture()
def client(migrated_engine, master_dir, monkeypatch):
    monkeypatch.setenv("ANALYTICAL_ACTIVE_PROVIDER", "stub")
    monkeypatch.setenv("ANALYTICAL_UPSTOX_MASTER_DIR", str(master_dir))
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


def test_catalog_finds_index_and_reports_available(client):
    r = client.get("/api/v1/instruments/catalog", params={"q": "nifty"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is True
    keys = {i["provider_symbol"] for i in body["items"]}
    assert "NSE_INDEX|Nifty 50" in keys
    idx = next(i for i in body["items"] if i["provider_symbol"] == "NSE_INDEX|Nifty 50")
    assert idx["instrument_type"] == "INDEX"
    assert idx["segment"] == "INDEX"
    assert idx["in_db"] is False


def test_catalog_type_filter_and_expiry_decode(client):
    r = client.get(
        "/api/v1/instruments/catalog", params={"q": "nifty", "instrument_type": "FUTURE"}
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items and all(i["instrument_type"] == "FUTURE" for i in items)
    fut = items[0]
    assert fut["expiry_date"] == "2026-09-29"
    assert fut["expiry_kind"] == "MONTHLY"
    assert fut["underlying_symbol"] == "NIFTY"


def test_catalog_option_carries_strike_and_type(client):
    r = client.get(
        "/api/v1/instruments/catalog", params={"q": "24000", "instrument_type": "OPTION"}
    )
    assert r.status_code == 200, r.text
    opt = r.json()["items"][0]
    assert opt["option_type"] == "CE"
    assert opt["strike_price"] == 24000.0
    assert opt["expiry_kind"] == "WEEKLY"


def test_catalog_marks_in_db_after_create(client):
    assert (
        client.post(
            "/api/v1/instruments",
            json={
                "instrument_type": "INDEX",
                "segment": "INDEX",
                "provider_symbol": "NSE_INDEX|Nifty 50",
                "symbol": "NIFTY",
            },
        ).status_code
        == 201
    )
    body = client.get("/api/v1/instruments/catalog", params={"q": "nifty"}).json()
    idx = next(i for i in body["items"] if i["provider_symbol"] == "NSE_INDEX|Nifty 50")
    assert idx["in_db"] is True


def test_catalog_short_query_rejected(client):
    assert client.get("/api/v1/instruments/catalog", params={"q": "n"}).status_code == 422


def test_catalog_missing_master_dir_reports_unavailable(client, monkeypatch, tmp_path):
    monkeypatch.setenv("ANALYTICAL_UPSTOX_MASTER_DIR", str(tmp_path / "does-not-exist"))
    get_settings.cache_clear()
    body = client.get("/api/v1/instruments/catalog", params={"q": "nifty"}).json()
    assert body["available"] is False
    assert body["items"] == []
