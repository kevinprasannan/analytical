"""Items 2-5 (DB) — schema/migration, scope constraints, FK behaviour, provenance.

The DDL-compile checks run with no database. The ``@pytest.mark.db`` checks run a
real ``alembic upgrade head`` against ``ANALYTICAL_TEST_DATABASE_URL`` and probe
the live catalog (docs/09 §2.8 — PostgreSQL only, never SQLite).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from analytical_core import enums
from app.db import models as m

BACKEND = Path(__file__).resolve().parents[1]
_PG = postgresql.dialect()


def _ddl() -> str:
    return "\n".join(
        str(CreateTable(t).compile(dialect=_PG)) for t in m.Base.metadata.sorted_tables
    )


# --- no-DB: DDL structure -------------------------------------------------


def test_all_tables_compile_for_postgres():
    # 19 market/ops tables + 3 astro side tables (docs/13) + index_weights (docs/15)
    assert len(m.Base.metadata.sorted_tables) == 23
    _ddl()  # must not raise


def test_scope_model_columns_and_checks_present():
    ddl = str(CreateTable(m.AnalysisResultRow.__table__).compile(dialect=_PG))
    assert "scope_key TEXT NOT NULL" in ddl
    assert "scope analysis_scope NOT NULL" in ddl
    assert "ck_analysis_results_scope_shape" in ddl
    assert "ck_analysis_results_scope_key_matches" in ddl
    assert "timeframe::text IN ('M5', 'M15', 'H1', 'D1')" in ddl


def test_current_projection_uses_collapsed_scope_ref():
    ddl = str(CreateTable(m.CurrentAnalysisResult.__table__).compile(dialect=_PG))
    assert "scope_ref TEXT NOT NULL" in ddl
    assert "PRIMARY KEY (instrument_id, analysis_key, scope_ref)" in ddl
    assert "ck_current_analysis_results_scope_ref_shape" in ddl


def test_analysis_key_check_matches_enum():
    ddl = str(CreateTable(m.AnalysisResultRow.__table__).compile(dialect=_PG))
    for v in enums.ANALYSIS_KEY_CHECK_VALUES:
        assert f"'{v}'" in ddl


def test_fk_ondelete_actions_match_docs03():
    ddl = _ddl()
    assert "FOREIGN KEY(run_id) REFERENCES analysis_runs (id) ON DELETE CASCADE" in ddl
    assert "FOREIGN KEY(signal_score_id) REFERENCES signal_scores (id) ON DELETE CASCADE" in ddl
    assert "REFERENCES instruments (id) ON DELETE RESTRICT" in ddl
    assert (
        "FOREIGN KEY(carried_from_result_id) REFERENCES analysis_results (id) "
        "ON DELETE SET NULL" in ddl
    )
    assert (
        "FOREIGN KEY(analysis_result_id) REFERENCES analysis_results (id) "
        "ON DELETE SET NULL" in ddl
    )


def test_self_underlying_check_present():
    ddl = str(CreateTable(m.Instrument.__table__).compile(dialect=_PG))
    assert "ck_instruments_no_self_underlying" in ddl


def test_provenance_columns_present_and_not_null():
    cols = {c.name: c for c in m.AnalysisResultRow.__table__.columns}
    for name in ("algo_version", "params_id", "params_hash"):
        assert name in cols and cols[name].nullable is False
    scols = {c.name: c for c in m.SignalScore.__table__.columns}
    assert scols["params_hash"].nullable is False


def test_offline_migration_renders_sql():
    """``alembic upgrade head --sql`` renders without a DB connection."""
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "CREATE TYPE analysis_scope AS ENUM" in out
    assert "CREATE TABLE analysis_results" in out
    # baseline create_all (now 22) + alembic_version + additive migrations that
    # re-emit under IF NOT EXISTS: 0002 (2), 0003 (1), 0005 index_weights (1)
    assert out.count("CREATE TABLE ") == 25


# --- DB: live catalog --------------------------------------------------


@pytest.mark.db
def test_migration_up_and_down_are_clean(db_url):
    from tests.conftest import _alembic

    assert _alembic(["downgrade", "base"], db_url).returncode == 0
    assert _alembic(["upgrade", "head"], db_url).returncode == 0
    assert _alembic(["downgrade", "base"], db_url).returncode == 0
    assert _alembic(["upgrade", "head"], db_url).returncode == 0


@pytest.mark.db
def test_migration_creates_all_tables(migrated_engine):
    from sqlalchemy import inspect

    names = set(inspect(migrated_engine).get_table_names())
    expected = {t.name for t in m.Base.metadata.sorted_tables} | {"alembic_version"}
    assert expected <= names


@pytest.mark.db
def test_scope_check_rejects_bad_combo(migrated_engine):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO analysis_runs (cycle_seq,trigger,status,phases_requested,"
                "algo_version,scoring_version,params_hash) "
                "VALUES (1,'MANUAL','RUNNING','{INGEST}','a','b','c')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO instruments (id,contract_key,symbol,segment,instrument_type,"
                "is_active,is_tracked) VALUES (1,'K','S','INDEX','INDEX',true,true)"
            )
        )
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            # PER_TIMEFRAME but timeframe NULL -> violates ck_analysis_results_scope_shape
            conn.execute(
                text(
                    "INSERT INTO analysis_results (run_id,instrument_id,analysis_key,scope,"
                    "scope_key,as_of_ts,status,algo_version,params_id,params_hash) "
                    "VALUES (1,1,'rsi','PER_TIMEFRAME','PER_TIMEFRAME:x',now(),'OK','a','b','c')"
                )
            )


@pytest.mark.db
def test_scope_check_accepts_all_three_scopes(migrated_engine):
    from sqlalchemy import text

    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO analysis_runs (id,cycle_seq,trigger,status,phases_requested,"
                "algo_version,scoring_version,params_hash) "
                "VALUES (2,2,'MANUAL','RUNNING','{ANALYZE}','a','b','c')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO instruments (id,contract_key,symbol,segment,instrument_type,"
                "is_active,is_tracked) VALUES (2,'K2','S2','FUT','FUTURE',true,true)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO analysis_results (run_id,instrument_id,analysis_key,scope,timeframe,"
                "scope_key,as_of_ts,status,algo_version,params_id,params_hash) "
                "VALUES (2,2,'rsi','PER_TIMEFRAME','M5','PER_TIMEFRAME:M5',now(),'OK','a','b','c')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO analysis_results (run_id,instrument_id,analysis_key,scope,session_date,"
                "scope_key,as_of_ts,status,algo_version,params_id,params_hash) "
                "VALUES (2,2,'market_profile','SESSION','2026-08-27','SESSION:2026-08-27',now(),"
                "'OK','a','b','c')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO analysis_results (run_id,instrument_id,analysis_key,scope,snapshot_ts,"
                "scope_key,as_of_ts,status,algo_version,params_id,params_hash) "
                "VALUES (2,2,'open_interest','SNAPSHOT',now(),"
                "'SNAPSHOT:2026-08-27T00:00:00+00:00',now(),'OK','a','b','c')"
            )
        )
        n = conn.execute(text("SELECT count(*) FROM analysis_results")).scalar_one()
        assert n == 3


@pytest.mark.db
def test_fk_restrict_blocks_instrument_delete_with_data(migrated_engine):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO instruments (id,contract_key,symbol,segment,instrument_type,"
                "is_active,is_tracked) VALUES (900,'K9','S9','INDEX','INDEX',true,true)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO ohlcv_bars (instrument_id,timeframe,ts,open,high,low,close,"
                "volume,provider,is_final) VALUES (900,'M5',now(),1,1,1,1,0,'stub',true)"
            )
        )
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(text("DELETE FROM instruments WHERE id = 900"))


@pytest.mark.db
def test_cascade_deletes_children_of_a_run(migrated_engine):
    from sqlalchemy import text

    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO analysis_runs (id,cycle_seq,trigger,status,phases_requested,"
                "algo_version,scoring_version,params_hash) "
                "VALUES (5,5,'MANUAL','SUCCEEDED','{SCORE}','a','b','c')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO instruments (id,contract_key,symbol,segment,instrument_type,"
                "is_active,is_tracked) VALUES (5,'K5','S5','INDEX','INDEX',true,true)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO run_phase_status (run_id,phase,status,counts,detail) "
                "VALUES (5,'SCORE','SUCCEEDED','{}','{}')"
            )
        )
        conn.execute(text("DELETE FROM analysis_runs WHERE id = 5"))
        left = conn.execute(
            text("SELECT count(*) FROM run_phase_status WHERE run_id = 5")
        ).scalar_one()
        assert left == 0
