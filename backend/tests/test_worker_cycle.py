"""Items 13-17 — worker cycle lifecycle (in-memory repositories).

  13 exactly one analysis_runs row per cycle
  14 phase statuses created
  15 partial instrument failure does not kill the cycle
  16 authentication failure -> SKIPPED behaviour, worker returns
  17 current_* projection populated + rebuildable
"""

from __future__ import annotations

from analytical_core.enums import (
    InstrumentPhaseOutcome,
    ProviderAuthState,
    RunPhase,
    RunStatus,
)
from app.db.repositories.memory import build_memory_repositories
from app.providers.stub import StubBehavior, StubProvider
from app.worker.cycle import run_cycle


def _repos(sample_instruments):
    return build_memory_repositories(sample_instruments)


def test_one_run_row_per_cycle(sample_instruments):
    repos, store = _repos(sample_instruments)
    provider = StubProvider(StubBehavior())
    r1 = run_cycle(repos, provider)
    r2 = run_cycle(repos, provider)
    assert store.runs and len(store.runs) == 2
    assert r1.cycle_seq == 1 and r2.cycle_seq == 2
    assert r1.run_id != r2.run_id
    assert repos.runs.count_runs() == 2


def test_phase_status_rows_created_for_every_phase(sample_instruments):
    repos, store = _repos(sample_instruments)
    result = run_cycle(repos, StubProvider(StubBehavior()))
    phases = {p for (_rid, p) in store.phase_status}
    assert phases == {RunPhase.INGEST, RunPhase.ANALYZE, RunPhase.SCORE}
    assert result.status is RunStatus.SUCCEEDED
    # per-(instrument, phase) outcome rows exist
    assert len(store.instrument_status) == len(sample_instruments) * 3


def test_analysis_and_scores_share_the_single_run_id(sample_instruments):
    repos, store = _repos(sample_instruments)
    result = run_cycle(repos, StubProvider(StubBehavior()))
    assert store.results and all(r.run_id == result.run_id for r in store.results)
    assert store.scores and all(s.run_id == result.run_id for s in store.scores)


def test_scope_model_exercised(sample_instruments):
    repos, store = _repos(sample_instruments)
    run_cycle(repos, StubProvider(StubBehavior()))
    scopes = {r.write.scope.value for r in store.results}
    assert scopes == {"PER_TIMEFRAME", "SESSION", "SNAPSHOT"}
    # NOT_APPLICABLE rows are persisted (index golden_cross / index OI)
    na = [r for r in store.results if r.write.status.value == "NOT_APPLICABLE"]
    assert na, "expected NOT_APPLICABLE rows to be persisted"


def test_partial_instrument_failure_does_not_kill_the_cycle(sample_instruments):
    repos, store = _repos(sample_instruments)
    # instrument 2's provider_symbol errors during INGEST
    behavior = StubBehavior(error_symbols=frozenset({"STUB:NIFTY-FUT-NEAR"}))
    result = run_cycle(repos, StubProvider(behavior))

    assert result.crashed is False
    assert result.status is RunStatus.PARTIAL
    assert store.instrument_status[(result.run_id, 2, RunPhase.INGEST)]["outcome"] is (
        InstrumentPhaseOutcome.ERROR
    )
    assert store.instrument_status[(result.run_id, 2, RunPhase.ANALYZE)]["outcome"] is (
        InstrumentPhaseOutcome.SKIPPED
    )
    # the other instruments still produced results + scores
    ok_ids = {1, 3}
    assert {r.write.instrument_id for r in store.results} == ok_ids
    assert {s.write.instrument_id for s in store.scores} == ok_ids


def test_authentication_failure_produces_skipped_and_returns(sample_instruments):
    repos, store = _repos(sample_instruments)
    provider = StubProvider(StubBehavior(auth_state=ProviderAuthState.EXPIRED))
    result = run_cycle(repos, provider)

    assert result.crashed is False
    assert result.status is RunStatus.PARTIAL  # completed, not FAILED, not a crash
    ingest = store.phase_status[(result.run_id, RunPhase.INGEST)]
    assert ingest["status"].value == "SKIPPED"
    for iid in (1, 2, 3):
        assert store.instrument_status[(result.run_id, iid, RunPhase.INGEST)]["outcome"] is (
            InstrumentPhaseOutcome.SKIPPED
        )
    # nothing analysed / scored for skipped instruments
    assert store.results == []
    assert store.scores == []


def test_current_projections_populated_and_rebuildable(sample_instruments):
    repos, store = _repos(sample_instruments)
    run_cycle(repos, StubProvider(StubBehavior()))
    snap_analysis = dict(store.current_analysis)
    snap_scores = dict(store.current_scores)
    assert snap_analysis and snap_scores

    repos.projections.rebuild_projections()
    assert store.current_analysis.keys() == snap_analysis.keys()
    assert store.current_scores.keys() == snap_scores.keys()
    for k in snap_analysis:
        assert (
            store.current_analysis[k]["analysis_result_id"]
            == snap_analysis[k]["analysis_result_id"]
        )


def test_delta_vs_previous_is_computed_across_runs(sample_instruments):
    repos, store = _repos(sample_instruments)
    run_cycle(repos, StubProvider(StubBehavior()))
    run_cycle(repos, StubProvider(StubBehavior()))
    # second run has a previous score -> delta is 0.0 (placeholder is constant), not None
    any_key = next(iter(store.current_scores))
    assert store.current_scores[any_key]["delta_vs_previous"] == 0.0


def test_score_only_phase_subset(sample_instruments):
    repos, store = _repos(sample_instruments)
    result = run_cycle(
        repos, StubProvider(StubBehavior()), phases=(RunPhase.ANALYZE, RunPhase.SCORE)
    )
    assert set(result.phases) == {RunPhase.ANALYZE, RunPhase.SCORE}
    assert (result.run_id, RunPhase.INGEST) not in store.phase_status
