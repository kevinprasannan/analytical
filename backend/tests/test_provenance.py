"""Item 5 — provenance fields (docs/04 §5, review M19)."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest

from analytical_core.enums import AnalysisScope, AnalysisStatus
from analytical_core.params import canonical_json, params_hash, params_id
from analytical_core.results import matrix_status_result


def test_params_hash_is_deterministic_and_16_hex():
    a = {"period": 14, "source": "close"}
    h1 = params_hash(a)
    h2 = params_hash({"source": "close", "period": 14})  # key order irrelevant
    assert h1 == h2
    assert re.fullmatch(r"[0-9a-f]{16}", h1)


def test_params_hash_changes_with_any_param():
    base = {"period": 14}
    assert params_hash(base) != params_hash({"period": 15})
    assert params_hash(base) != params_hash({"period": 14, "extra": 1})


def test_params_hash_rejects_non_mapping_and_nan():
    with pytest.raises(TypeError):
        params_hash([1, 2, 3])  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        canonical_json(float("nan"))


def test_params_id_shape():
    assert params_id("rsi") == "rsi.v1"
    assert params_id("bollinger", "v2") == "bollinger.v2"


def test_matrix_status_result_carries_full_provenance():
    r = matrix_status_result(
        analysis_key="rsi", scope=AnalysisScope.PER_TIMEFRAME, as_of_ts=datetime.now(tz=UTC)
    )
    assert r.status is AnalysisStatus.OK
    assert r.values == {}  # no engine ran -> no computed values
    assert set(r.meta) == {"algo_version", "params_id", "params_hash"}
    assert re.fullmatch(r"[0-9a-f]{16}", r.meta["params_hash"])
    from analytical_core.versioning import ALGO_VERSION

    assert r.meta["algo_version"] == ALGO_VERSION


def test_matrix_status_not_applicable_carries_reason():
    r = matrix_status_result(
        analysis_key="golden_cross",
        scope=AnalysisScope.PER_TIMEFRAME,
        as_of_ts=datetime.now(tz=UTC),
        status=AnalysisStatus.NOT_APPLICABLE,
        reason="dated contract",
    )
    assert r.status is AnalysisStatus.NOT_APPLICABLE
    assert r.values["reason"] == "dated contract"
    assert any("NOT_APPLICABLE" in w for w in r.warnings)


def test_matrix_status_insufficient_data_carries_reason():
    r = matrix_status_result(
        analysis_key="open_interest",
        scope=AnalysisScope.PER_TIMEFRAME,
        as_of_ts=datetime.now(tz=UTC),
        status=AnalysisStatus.INSUFFICIENT_DATA,
        reason="no OI feed for this instrument",
    )
    assert r.status is AnalysisStatus.INSUFFICIENT_DATA
    assert r.values["reason"] == "no OI feed for this instrument"
    assert r.warnings == ("open_interest INSUFFICIENT_DATA: no OI feed for this instrument",)
    assert "phase1_scaffold" not in r.meta and "phase1_scaffold" not in r.values
