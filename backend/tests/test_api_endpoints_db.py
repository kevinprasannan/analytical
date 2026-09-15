"""API layer — endpoints over a populated PostgreSQL (``@pytest.mark.db``)."""

from __future__ import annotations

import math as _math
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from analytical_core.enums import InstrumentSegment, InstrumentType
from analytical_core.versioning import ALGO_VERSION
from app.api.deps import get_db
from app.api.main import create_app
from app.config import Settings, get_settings
from app.db import models as md
from app.db.repositories.sqlalchemy import build_sqlalchemy_repositories
from app.providers.upstox import UpstoxProvider
from app.providers.upstox.http import UpstoxHTTPClient
from app.worker.cycle import run_cycle

pytestmark = pytest.mark.db

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _m1(n, sm=555):
    rows = [
        [
            f"2026-08-27T{(sm + i) // 60:02d}:{(sm + i) % 60:02d}:00+05:30",
            100 + (i % 7),
            101 + (i % 7),
            99 + (i % 7),
            100 + (i % 5),
            10 + i,
            54000 + i,
        ]
        for i in range(n)
    ]
    rows.reverse()
    return rows


def _provider():
    def handler(req):
        c = (
            [["2026-08-25T00:00:00+05:30", 100, 105, 95, 102, 5000, 0]]
            if "/days/1/" in str(req.url)
            else _m1(200)
        )
        return httpx.Response(200, json={"status": "success", "data": {"candles": c}})

    cl = UpstoxHTTPClient(
        base_url="https://api.upstox.com",
        token_provider=lambda: "t",
        transport=httpx.MockTransport(handler),
        max_rps=0,
        max_retries=0,
        sleep_fn=lambda _s: None,
    )
    return UpstoxProvider(
        Settings(active_provider="upstox", upstox_access_token="x"), http_client=cl
    )


@pytest.fixture()
def client(migrated_engine, monkeypatch):
    monkeypatch.setenv("ANALYTICAL_ACTIVE_PROVIDER", "upstox")
    get_settings.cache_clear()

    with Session(migrated_engine) as seed:
        fut = md.Instrument(
            contract_key="NIFTY-FUT-2026-09",
            symbol="NIFTY",
            segment=InstrumentSegment.FUT,
            instrument_type=InstrumentType.FUTURE,
            is_tracked=True,
        )
        idx = md.Instrument(
            contract_key="NIFTY-INDEX",
            symbol="NIFTY",
            segment=InstrumentSegment.INDEX,
            instrument_type=InstrumentType.INDEX,
            is_tracked=True,
        )
        seed.add_all([fut, idx])
        seed.flush()
        seed.add(
            md.ProviderInstrumentMap(
                instrument_id=fut.id,
                provider="upstox",
                provider_symbol="NSE_FO|68407",
                is_active=True,
            )
        )
        seed.add(
            md.ProviderInstrumentMap(
                instrument_id=idx.id,
                provider="upstox",
                provider_symbol="NSE_INDEX|Nifty 50",
                is_active=True,
            )
        )
        seed.commit()
        fut_id, idx_id = fut.id, idx.id
        run_cycle(
            build_sqlalchemy_repositories(seed),
            _provider(),
            settings=Settings(active_provider="upstox"),
            now_fn=lambda: NOW,
        )
        seed.commit()

    app = create_app()

    def _override_db():
        s = Session(migrated_engine)
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override_db
    c = TestClient(app)
    c.fut_id, c.idx_id = fut_id, idx_id
    yield c
    get_settings.cache_clear()


# ======================================================================================


def test_instruments_list_and_detail(client):
    body = client.get("/api/v1/instruments?is_tracked=true").json()
    assert body["total"] == 2 and len(body["items"]) == 2

    detail = client.get(f"/api/v1/instruments/{client.fut_id}").json()
    assert detail["contract_key"] == "NIFTY-FUT-2026-09"
    assert detail["provider_map"][0]["provider_symbol"] == "NSE_FO|68407"
    assert "rsi" in detail["applicable_analyses"]
    assert "golden_cross" not in detail["applicable_analyses"]  # NA for FUTURE


def test_instrument_404_is_problem_json(client):
    r = client.get("/api/v1/instruments/999999")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["title"] == "Not Found"


def test_validation_error_is_422_problem_json(client):
    r = client.get(f"/api/v1/instruments/{client.fut_id}/bars?timeframe=NOPE")
    assert r.status_code == 422
    body = r.json()
    assert body["status"] == 422 and "errors" in body


def test_patch_is_tracked_toggle(client):
    r = client.patch(f"/api/v1/instruments/{client.idx_id}", json={"is_tracked": False})
    assert r.status_code == 200 and r.json()["is_tracked"] is False
    again = client.get(f"/api/v1/instruments/{client.idx_id}").json()
    assert again["is_tracked"] is False


def test_bars_and_coverage(client):
    bars = client.get(f"/api/v1/instruments/{client.fut_id}/bars?timeframe=M5&limit=10").json()
    assert bars["timeframe"] == "M5" and bars["total"] > 0
    assert bars["items"] == sorted(bars["items"], key=lambda b: b["ts"])  # ascending

    cov = client.get(f"/api/v1/instruments/{client.fut_id}/coverage").json()
    by_tf = {c["timeframe"]: c for c in cov["timeframes"]}
    assert by_tf["M1"]["bar_count"] == 200
    assert by_tf["M5"]["bar_count"] == 40
    assert by_tf["M1"]["watermark_status"] == "OK"
    assert cov["last_oi"] is not None


def test_open_interest_index_is_200_not_applicable(client):
    r = client.get(f"/api/v1/instruments/{client.idx_id}/open-interest")
    assert r.status_code == 200
    assert r.json()["status"] == "NOT_APPLICABLE"

    fo = client.get(
        f"/api/v1/instruments/{client.fut_id}/open-interest?timeframe=M1&limit=5"
    ).json()
    assert fo["status"] == "OK" and fo["total"] == 200


def test_analyses_list_and_detail_and_series(client):
    lst = client.get("/api/v1/analyses?timeframe=M5&analysis_key=rsi").json()
    assert lst["total"] >= 1
    item = lst["items"][0]
    assert item["scope"] == "PER_TIMEFRAME" and item["timeframe"] == "M5"

    one = client.get(f"/api/v1/instruments/{client.fut_id}/analyses/rsi?timeframe=M5").json()
    assert one["status"] == "OK"
    assert 0.0 <= one["typed_values"]["rsi"] <= 100.0
    assert one["provenance"]["algo_version"] == ALGO_VERSION

    inst = client.get(f"/api/v1/instruments/{client.fut_id}/analyses?timeframe=M5").json()
    keys = {i["analysis_key"] for i in inst["items"]}
    assert {"rsi", "bollinger", "ema7", "volume"} <= keys

    ser = client.get(f"/api/v1/instruments/{client.fut_id}/analyses/rsi/series?timeframe=M5").json()
    assert ser["points"] and "values" in ser["points"][0]

    runs = client.get(f"/api/v1/instruments/{client.fut_id}/analyses/rsi/runs").json()
    assert runs["runs"] and runs["runs"][0]["run_id"] >= 1


def test_golden_cross_future_analysis_is_not_applicable_via_api(client):
    one = client.get(
        f"/api/v1/instruments/{client.fut_id}/analyses/golden_cross?timeframe=D1"
    ).json()
    assert one["status"] == "NOT_APPLICABLE"
    assert one["reason"]


def test_non_per_timeframe_analysis_reachable_without_a_timeframe(client):
    # market_profile is SESSION-scoped: the detail endpoint works with no ?timeframe=
    mp = client.get(f"/api/v1/instruments/{client.fut_id}/analyses/market_profile")
    assert mp.status_code == 200
    assert mp.json()["scope"] == "SESSION"
    # ?timeframe= is tolerated (ignored) for a non-per-timeframe analysis
    with_tf = client.get(
        f"/api/v1/instruments/{client.fut_id}/analyses/market_profile?timeframe=M5"
    )
    assert with_tf.status_code == 200 and with_tf.json()["scope"] == "SESSION"

    # a per-timeframe analysis still needs (and honours) ?timeframe=
    assert client.get(f"/api/v1/instruments/{client.fut_id}/analyses/rsi").status_code == 404
    assert (
        client.get(f"/api/v1/instruments/{client.fut_id}/analyses/rsi?timeframe=M5").status_code
        == 200
    )


def test_runs_list_and_detail(client):
    lst = client.get("/api/v1/runs").json()
    assert lst["total"] == 1
    rid = lst["items"][0]["id"]
    detail = client.get(f"/api/v1/runs/{rid}").json()
    phases = {p["phase"] for p in detail["phase_status"]}
    assert phases == {"INGEST", "ANALYZE", "SCORE"}
    assert detail["instrument_status"]
    assert detail["params_hash"]


def test_scores_list_and_detail_and_history(client):
    lst = client.get("/api/v1/scores?timeframe=M5").json()
    assert lst["total"] >= 1
    item = next(i for i in lst["items"] if i["instrument_id"] == client.fut_id)
    assert item["effective_label"] in {
        "STRONG_BEARISH",
        "BEARISH",
        "NEUTRAL",
        "BULLISH",
        "STRONG_BULLISH",
    }
    assert -100.0 <= item["composite_score"] <= 100.0

    detail = client.get(f"/api/v1/instruments/{client.fut_id}/score?timeframe=M5").json()
    assert detail["scoring_version"] == "1.0.0"
    assert detail["strategy"] == "weighted_v1"
    assert detail["explanation"]
    assert detail["factors"]  # real analyses fed the score
    csum = _math.fsum(f["contribution"] for f in detail["factors"])
    assert abs(csum - detail["composite_score"]) < 1e-3
    assert detail["weights"]["rsi"] == 1.0

    hist = client.get(f"/api/v1/instruments/{client.fut_id}/score/history?timeframe=M5").json()
    assert hist["points"] and hist["points"][-1]["run_id"] >= 1


def test_score_404_when_no_score_for_timeframe(client):
    r = client.get("/api/v1/instruments/999999/score?timeframe=M5")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
