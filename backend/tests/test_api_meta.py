"""API scaffold — /meta/enums, /meta/versions, /health (no DB needed)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from analytical_core import enums
from app.api.main import create_app

client = TestClient(create_app())


def test_health_ok():
    r = client.get("/api/v1/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_meta_enums_matches_authoritative_contract():
    r = client.get("/api/v1/meta/enums")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == set(enums.ENUM_REGISTRY)
    assert body["analysis_scope"]["values"] == ["PER_TIMEFRAME", "SESSION", "SNAPSHOT"]
    assert body["signal_label"]["values"][0] == "STRONG_BEARISH"


def test_meta_timeframes_are_user_facing_only():
    r = client.get("/api/v1/meta/timeframes")
    assert r.json() == {"user_facing": ["M5", "M15", "H1", "D1"]}


def test_meta_applicability_matrix():
    body = client.get("/api/v1/meta/applicability").json()
    assert body["golden_cross"]["FUTURE"] == "NA"
    assert body["golden_cross"]["INDEX"] == "OK"
    assert body["open_interest"]["INDEX"] == "NA"
    assert body["market_profile"]["scope"] == "SESSION"


def test_openapi_generates_and_binds_enums():
    spec = client.get("/openapi.json").json()
    schemas = spec["components"]["schemas"]
    assert schemas["RSIState"]["enum"] == [s.value for s in enums.RSIState]
    assert schemas["OIBehavior"]["enum"] == [s.value for s in enums.OIBehavior]
    assert "Divergence" in schemas


def test_meta_versions_reported():
    from analytical_core.versioning import ALGO_VERSION, SCORING_VERSION

    r = client.get("/api/v1/meta/versions")
    body = r.json()
    assert body["algo_version"] == ALGO_VERSION  # Phase 3 engine + Market Profile
    assert body["scoring_version"] == SCORING_VERSION
    assert body["active_provider"] == "stub"
    # shape contract (the actual counts depend on whatever DB is reachable)
    assert isinstance(body["stale_results"], bool)
    assert set(body["stale_result_counts"]) == {"analysis_results", "signal_scores"}
    assert all(isinstance(v, int) for v in body["stale_result_counts"].values())
    assert len(body["config_params_hash"]) == 16
    assert body["git_sha"] is None


def test_auth_seam_enforced_when_token_set(monkeypatch):
    monkeypatch.setenv("ANALYTICAL_LOCAL_API_TOKEN", "secret")
    from app.config import get_settings

    get_settings.cache_clear()
    from app.api import deps

    app = create_app()
    app.dependency_overrides = {}
    # meta/health routers don't require the principal in Phase 1, so assert the
    # dependency itself behaves (unit-level).
    import fastapi

    with_token = deps.get_current_principal(authorization="Bearer secret")
    assert with_token.username == "owner"
    try:
        deps.get_current_principal(authorization=None)
        raised = False
    except fastapi.HTTPException as exc:
        raised = exc.status_code == 401
    assert raised
    get_settings.cache_clear()
