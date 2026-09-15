"""Item 1 — the authoritative enum contract (docs/12, docs/09 §2.6).

Without a live DB we verify: the Python source of truth is self-consistent, the
``emit_sql`` / ``emit_json`` derivations agree with it, the DB-materialised subset
matches the tables that use enum columns, and the registry covers exactly the
docs/12 §4 contract names. The Python == PG-labels leg additionally runs under
``@pytest.mark.db`` when a database is available.
"""

from __future__ import annotations

import re

import pytest

from analytical_core import enums

DOCS12_CONTRACT_NAMES = {
    "timeframe",
    "instrument_type",
    "instrument_segment",
    "option_type",
    "expiry_kind",
    "data_kind",
    "analysis_scope",
    "analysis_key",
    "analysis_status",
    "profile_type",
    "market_profile_shape",
    "oi_behavior",
    "direction",
    "bollinger_position",
    "ma_slope_state",
    "rsi_state",
    "golden_cross_type",
    "divergence",
    "volume_trend",
    "volume_up_down_state",
    "order_block_bias",
    "order_block_zone_state",
    "candle_pattern",
    "candle_bias",
    "candle_strength",
    "signal_label",
    "scoring_strategy",
    "run_trigger",
    "run_status",
    "run_phase",
    "phase_status",
    "instrument_phase_outcome",
    "watermark_status",
    "provider_auth_state",
}


def test_registry_matches_docs12_contract_names():
    assert set(enums.ENUM_REGISTRY) == DOCS12_CONTRACT_NAMES


def test_values_are_unique_and_str():
    for name, cls in enums.ENUM_REGISTRY.items():
        vals = [m.value for m in cls]
        assert len(vals) == len(set(vals)), name
        assert all(isinstance(v, str) and v for v in vals), name


def test_analysis_key_is_lowercase_others_upper():
    for v in enums.values("analysis_key"):
        assert v == v.lower()
    for name in enums.ENUM_REGISTRY:
        if name == "analysis_key":
            continue
        for v in enums.values(name):
            if name == "scoring_strategy":
                continue  # documented lowercase strategy id
            assert v == v.upper(), (name, v)


def test_emit_sql_matches_python_values_for_db_enums():
    sql = enums.emit_sql()
    for name in enums.DB_ENUMS:
        m = re.search(rf"CREATE TYPE {name} AS ENUM \((.+?)\);", sql)
        assert m, name
        labels = [s.strip().strip("'") for s in m.group(1).split(",")]
        assert labels == enums.values(name)


def test_emit_json_covers_registry_and_flags_db_subset():
    j = enums.emit_json()
    assert set(j) == set(enums.ENUM_REGISTRY)
    for name, entry in j.items():
        assert entry["values"] == enums.values(name)
        assert entry["materialized_in_db"] == (name in enums.DB_ENUMS)


def test_db_enums_are_exactly_the_columns_that_use_them():
    """Every ``pg_enum`` in the models must be a DB_ENUM, and vice versa."""
    from sqlalchemy import Enum as SAEnum

    from app.db import models as m

    used: set[str] = set()
    for table in m.Base.metadata.sorted_tables:
        for col in table.columns:
            if isinstance(col.type, SAEnum) and col.type.name:
                used.add(col.type.name)
    assert used == set(enums.DB_ENUMS)


def test_user_facing_timeframes_exclude_m1():
    assert enums.Timeframe.M1 not in enums.USER_FACING_TIMEFRAMES
    assert set(enums.USER_FACING_TIMEFRAMES) == {
        enums.Timeframe.M5,
        enums.Timeframe.M15,
        enums.Timeframe.H1,
        enums.Timeframe.D1,
    }


@pytest.mark.db
def test_python_values_equal_pg_enum_labels(migrated_engine):
    """docs/09 §2.6 — the Python source of truth == the PG enum labels created
    by the baseline migration, for every DB-materialised enum."""
    from sqlalchemy import text

    with migrated_engine.connect() as conn:
        for name in enums.DB_ENUMS:
            rows = (
                conn.execute(
                    text(
                        "SELECT e.enumlabel FROM pg_enum e "
                        "JOIN pg_type t ON t.oid = e.enumtypid "
                        "WHERE t.typname = :n ORDER BY e.enumsortorder"
                    ),
                    {"n": name},
                )
                .scalars()
                .all()
            )
            assert list(rows) == enums.values(name), name
