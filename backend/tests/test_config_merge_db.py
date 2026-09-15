"""``app_settings`` -> effective engine config through ``run_cycle`` (``@pytest.mark.db``).

A ``PATCH /config`` write lands in ``app_settings``; the next cycle must fold it
into the effective ``ScoringConfig`` / ``MarketProfileConfig`` and record it on
the run (docs/06 §7, docs/05 §10.1).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from analytical_core.enums import InstrumentSegment, InstrumentType
from app.config import Settings
from app.db import models as md
from app.db.repositories.sqlalchemy import build_sqlalchemy_repositories
from app.providers.upstox import UpstoxProvider
from app.providers.upstox.http import UpstoxHTTPClient
from app.settings_store import load_app_settings
from app.worker.cycle import run_cycle

pytestmark = pytest.mark.db

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


@pytest.fixture()
def db_session(migrated_engine):
    with Session(migrated_engine) as s:
        yield s


def _m1(n=200, sm=555):
    """A wide ~24000 ± 150 hump so the session range spans many profile bins."""
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
        c = (
            [["2026-08-25T00:00:00+05:30", 24000, 24100, 23900, 24050, 5000, 0]]
            if "/days/1/" in str(req.url)
            else _m1()
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


def _tracked(db):
    inst = md.Instrument(
        contract_key="NIFTY-FUT-2026-09",
        symbol="NIFTY",
        segment=InstrumentSegment.FUT,
        instrument_type=InstrumentType.FUTURE,
        is_tracked=True,
    )
    db.add(inst)
    db.flush()
    db.add(
        md.ProviderInstrumentMap(
            instrument_id=inst.id,
            provider="upstox",
            provider_symbol="NSE_FO|68407",
            is_active=True,
        )
    )
    db.flush()
    return int(inst.id)


def _seed_setting(db, key, value):
    db.add(md.AppSetting(key=key, value=value))
    db.flush()


def _run(db, app_settings=None):
    return run_cycle(
        build_sqlalchemy_repositories(db),
        _provider(),
        settings=Settings(active_provider="upstox"),
        app_settings=app_settings,
        now_fn=lambda: NOW,
    )


def test_load_app_settings_returns_the_flat_key_value_map(db_session):
    _seed_setting(db_session, "scoring.min_confidence", 0.5)
    _seed_setting(db_session, "market_profile.tpo_minutes", 60)
    db_session.commit()
    loaded = load_app_settings(db_session)
    assert loaded == {"scoring.min_confidence": 0.5, "market_profile.tpo_minutes": 60}


def test_bumped_scoring_weight_flows_into_signal_scores_and_the_run(db_session):
    _tracked(db_session)
    _seed_setting(db_session, "scoring.weights", {"rsi": 9.0})
    db_session.commit()

    baseline = _run(db_session)
    db_session.commit()
    base_hashes = {
        s.params_hash
        for s in db_session.execute(
            select(md.SignalScore).where(md.SignalScore.run_id == baseline.run_id)
        ).scalars()
    }

    result = _run(db_session, app_settings=load_app_settings(db_session))
    db_session.commit()

    scores = list(
        db_session.execute(
            select(md.SignalScore).where(md.SignalScore.run_id == result.run_id)
        ).scalars()
    )
    assert scores
    for s in scores:
        assert s.weights["rsi"] == 9.0
        assert s.weights["golden_cross"] == 1.5  # untouched default
        assert s.params_hash not in base_hashes  # config folded into provenance

    run = db_session.get(md.AnalysisRun, result.run_id)
    assert run.config_snapshot["scoring"]["weights"]["rsi"] == 9.0
    assert "market_profile" in run.config_snapshot
    base_run = db_session.get(md.AnalysisRun, baseline.run_id)
    assert run.params_hash != base_run.params_hash


def test_no_app_settings_keeps_engine_defaults(db_session):
    _tracked(db_session)
    db_session.commit()
    result = _run(db_session, app_settings=None)
    db_session.commit()
    s = (
        db_session.execute(select(md.SignalScore).where(md.SignalScore.run_id == result.run_id))
        .scalars()
        .first()
    )
    assert s.weights["rsi"] == 1.0


def _mp_result(db, run_id):
    return db.execute(
        select(md.AnalysisResultRow).where(
            md.AnalysisResultRow.run_id == run_id,
            md.AnalysisResultRow.analysis_key == "market_profile",
        )
    ).scalar_one()


def test_market_profile_tpo_minutes_override_reaches_the_engine(db_session):
    _tracked(db_session)
    db_session.commit()

    base = _run(db_session)
    db_session.commit()
    base_ar = _mp_result(db_session, base.run_id)
    base_params_hash = base_ar.params_hash
    base_session_hash = (
        db_session.execute(select(md.MarketProfileSession.params_hash)).scalars().first()
    )

    _seed_setting(db_session, "market_profile.tpo_minutes", 60)
    db_session.commit()
    result = _run(db_session, app_settings=load_app_settings(db_session))
    db_session.commit()

    run = db_session.get(md.AnalysisRun, result.run_id)
    assert run.config_snapshot["market_profile"]["tpo_minutes"] == 60

    ar = _mp_result(db_session, result.run_id)
    assert ar.result["meta"]["params"]["tpo_minutes"] == 60
    assert ar.params_hash != base_params_hash  # config folded into provenance

    # sessions are upserted by (instrument, date, profile_type) -> re-read same rows
    db_session.expire_all()
    new_session_hash = (
        db_session.execute(select(md.MarketProfileSession.params_hash)).scalars().first()
    )
    assert new_session_hash is not None and new_session_hash != base_session_hash
