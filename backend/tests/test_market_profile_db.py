"""Market Profile — through ``run_cycle`` on PostgreSQL + the API (``@pytest.mark.db``)."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from analytical_core.enums import InstrumentSegment, InstrumentType
from app.api.deps import get_db
from app.api.main import create_app
from app.config import Settings, get_settings
from app.db import models as md
from app.db.repositories.sqlalchemy import build_sqlalchemy_repositories
from app.providers.upstox import UpstoxProvider
from app.providers.upstox.http import UpstoxHTTPClient
from app.worker.cycle import run_cycle

pytestmark = pytest.mark.db

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)  # after the 09:15-15:30 IST session


def _m1(n=200, sm=555):
    # a wide hump ~24000 ± 150 so the session range spans many bins
    rows = []
    for i in range(n):
        t = sm + i
        c = 24000.0 + 150.0 * math.exp(-((i - n / 2) ** 2) / (2 * (n / 6) ** 2))
        rows.append(
            [
                f"2026-08-27T{t // 60:02d}:{t % 60:02d}:00+05:30",
                c,
                c + 6,
                c - 6,
                c,
                100 + i,
                54000 + i,
            ]
        )
    rows.reverse()
    return rows


def _provider():
    def handler(req):
        candles = (
            [["2026-08-25T00:00:00+05:30", 24000, 24100, 23900, 24050, 5000, 0]]
            if "/days/1/" in str(req.url)
            else _m1()
        )
        return httpx.Response(200, json={"status": "success", "data": {"candles": candles}})

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
                instrument_id=inst.id,
                provider="upstox",
                provider_symbol="NSE_FO|68407",
                is_active=True,
            )
        )
        seed.commit()
        iid = inst.id
        result = run_cycle(
            build_sqlalchemy_repositories(seed),
            _provider(),
            settings=Settings(active_provider="upstox"),
            now_fn=lambda: NOW,
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
    c = TestClient(app)
    c.iid = iid
    c.run_id = result.run_id
    yield c
    get_settings.cache_clear()


def test_market_profile_sessions_and_analysis_row_written(client, migrated_engine):
    with Session(migrated_engine) as db:
        sessions = db.execute(select(md.MarketProfileSession)).scalars().all()
        assert {s.profile_type.value for s in sessions} == {"TPO", "VOLUME"}
        tpo = next(s for s in sessions if s.profile_type.value == "TPO")
        assert tpo.poc is not None and tpo.vah is not None and tpo.val is not None
        assert float(tpo.val) <= float(tpo.poc) <= float(tpo.vah)
        assert tpo.is_session_complete is True
        assert tpo.bins and tpo.bins["bins"]
        assert len(tpo.params_hash) == 16

        ar = db.execute(
            select(md.AnalysisResultRow).where(
                md.AnalysisResultRow.analysis_key == "market_profile"
            )
        ).scalar_one()
        assert ar.status.value == "OK"
        assert ar.scope.value == "SESSION"
        assert ar.result["values"]["profile_shape"] in {
            "NORMAL",
            "P_SHAPE",
            "B_SHAPE",
            "DOUBLE_DISTRIBUTION",
            "TREND_UP",
            "TREND_DOWN",
        }


def test_market_profile_factor_now_contributes_to_the_score(client, migrated_engine):
    with Session(migrated_engine) as db:
        keys = set(
            db.execute(
                select(md.ScoreFactor.analysis_key)
                .join(md.SignalScore, md.SignalScore.id == md.ScoreFactor.signal_score_id)
                .where(md.SignalScore.run_id == client.run_id)
            ).scalars()
        )
    assert "market_profile" in keys  # sub-score activated (docs/06 §3.1)


def test_market_profile_api(client):
    r = client.get(f"/api/v1/instruments/{client.iid}/market-profile")
    assert r.status_code == 200
    body = r.json()
    assert body["session_date"] == "2026-08-27"
    assert body["is_session_complete"] is True
    assert body["val"] <= body["poc"] <= body["vah"]
    assert set(body["profiles"]) == {"TPO", "VOLUME"}
    assert body["profiles"]["TPO"]["bins"]
    assert body["close"] is not None and body["close_vs_poc"] in {"ABOVE", "AT", "BELOW"}

    only_tpo = client.get(
        f"/api/v1/instruments/{client.iid}/market-profile?profile_type=TPO"
    ).json()
    assert set(only_tpo["profiles"]) == {"TPO"}


def test_market_profile_event_layer_blob_written(client, migrated_engine):
    with Session(migrated_engine) as db:
        tpo = next(
            s
            for s in db.execute(select(md.MarketProfileSession)).scalars().all()
            if s.profile_type.value == "TPO"
        )
        assert tpo.close is not None
        assert tpo.mp_events_version and tpo.mp_events_version.count(".") == 2
        ev = tpo.events
        assert isinstance(ev, dict)
        assert ev["status"] in {"OK", "INSUFFICIENT_DATA"}
        assert ev["version"] == tpo.mp_events_version
        if ev["status"] == "OK":
            assert isinstance(ev["events"], list) and ev["events"]
            # opening events always present (they're CONTEXT, no prior needed)
            assert {"MP-001", "MP-002", "MP-003"} <= {e["id"] for e in ev["events"]}
            assert ev["day_type"]["day_type"] in {
                "NORMAL",
                "NORMAL_VARIATION",
                "TREND_UP",
                "TREND_DOWN",
                "DOUBLE_DISTRIBUTION",
                "NEUTRAL",
                "NEUTRAL_EXTREME",
                "RANGE",
                "LARGE_RANGE",
                "UNDETERMINED",
            }
            for e in ev["events"]:
                assert e["state"] in {
                    "NOT_TRIGGERED",
                    "TRIGGERED",
                    "DEVELOPING",
                    "CONFIRMED",
                    "INVALIDATED",
                    "EXPIRED",
                }
                assert e["strength"] in {"STRONG", "MODERATE", "WEAK", "CONTEXT"}


def test_market_profile_api_includes_event_block(client):
    body = client.get(f"/api/v1/instruments/{client.iid}/market-profile").json()
    assert "events" in body
    ev = body["events"]
    assert ev is not None
    assert ev["status"] in {"OK", "INSUFFICIENT_DATA"}
    assert isinstance(ev["events"], list)
    if ev["status"] == "OK":
        assert ev["day_type"]["silhouette"] in {
            "BALANCED_D",
            "P_SHAPE",
            "B_SHAPE",
            "THIN_I",
            "BIMODAL",
            "UNDETERMINED",
        }


def test_market_profile_recompute_guard_carries_on_second_cycle(client, migrated_engine):
    with Session(migrated_engine) as db:
        n_before = db.execute(
            select(func.count()).select_from(md.MarketProfileSession)
        ).scalar_one()
        run_cycle(
            build_sqlalchemy_repositories(db),
            _provider(),
            settings=Settings(active_provider="upstox"),
            now_fn=lambda: NOW,
        )
        db.commit()
        n_after = db.execute(select(func.count()).select_from(md.MarketProfileSession)).scalar_one()
        assert n_after == n_before  # upsert, no new rows
        carried = (
            db.execute(
                select(md.AnalysisResultRow).where(
                    md.AnalysisResultRow.analysis_key == "market_profile",
                    md.AnalysisResultRow.carried.is_(True),
                )
            )
            .scalars()
            .all()
        )
        assert carried  # unchanged source_max_ts + params_hash -> carried
