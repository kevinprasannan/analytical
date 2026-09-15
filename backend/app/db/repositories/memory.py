"""Deterministic in-memory repositories (tests + local dev without a database)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from analytical_core.enums import (
    AnalysisScope,
    RunPhase,
    RunStatus,
    RunTrigger,
)
from app.db.repositories.market_data import MemoryMarketDataRepository
from app.db.repositories.market_profile import MemoryMarketProfileRepository
from app.db.repositories.protocols import (
    FactorWrite,
    InstrumentView,
    Repositories,
    ResultWrite,
    ScoreWrite,
)


@dataclass(slots=True)
class _Run:
    id: int
    cycle_seq: int
    trigger: RunTrigger
    phases_requested: list[str]
    algo_version: str
    scoring_version: str
    config_snapshot: dict
    params_hash: str
    status: RunStatus = RunStatus.RUNNING
    finished_at: datetime | None = None


@dataclass(slots=True)
class _StoredResult:
    id: int
    run_id: int
    write: ResultWrite


@dataclass(slots=True)
class _StoredScore:
    id: int
    run_id: int
    write: ScoreWrite


class MemoryStore:
    """Backing store shared by the in-memory repositories."""

    def __init__(self, tracked: list[InstrumentView] | None = None) -> None:
        self.tracked: list[InstrumentView] = list(tracked or [])
        self.runs: dict[int, _Run] = {}
        self.phase_status: dict[tuple[int, RunPhase], dict] = {}
        self.instrument_status: dict[tuple[int, int, RunPhase], dict] = {}
        self.results: list[_StoredResult] = []
        self.scores: list[_StoredScore] = []
        self.factors: dict[int, list[FactorWrite]] = {}
        self.current_analysis: dict[tuple[int, str, str], dict] = {}
        self.current_scores: dict[tuple[int, str], dict] = {}
        self._run_seq = 0
        self._result_seq = 0
        self._score_seq = 0
        self._cycle_seq = 0


class MemoryRunRepository:
    def __init__(self, store: MemoryStore) -> None:
        self.s = store

    def next_cycle_seq(self) -> int:
        self.s._cycle_seq += 1
        return self.s._cycle_seq

    def create_run(self, **kw) -> int:
        self.s._run_seq += 1
        rid = self.s._run_seq
        self.s.runs[rid] = _Run(id=rid, **kw)
        return rid

    def set_phase_status(
        self, run_id, phase, status, *, counts, started_at, finished_at, detail=None
    ) -> None:
        self.s.phase_status[(run_id, phase)] = {
            "status": status,
            "counts": counts,
            "started_at": started_at,
            "finished_at": finished_at,
            "detail": detail or {},
        }

    def set_instrument_status(self, run_id, instrument_id, phase, outcome, detail=None) -> None:
        self.s.instrument_status[(run_id, instrument_id, phase)] = {
            "outcome": outcome,
            "detail": detail or {},
        }

    def finalize_run(self, run_id, status, finished_at) -> None:
        self.s.runs[run_id].status = status
        self.s.runs[run_id].finished_at = finished_at

    def get_run_status(self, run_id) -> RunStatus:
        return self.s.runs[run_id].status

    def count_runs(self) -> int:
        return len(self.s.runs)


class MemoryInstrumentRepository:
    def __init__(self, store: MemoryStore) -> None:
        self.s = store

    def list_tracked(self) -> list[InstrumentView]:
        return list(self.s.tracked)


class MemoryAnalysisResultRepository:
    def __init__(self, store: MemoryStore) -> None:
        self.s = store

    def upsert_result(self, run_id: int, write: ResultWrite) -> int:
        # natural key: (run_id, instrument_id, analysis_key, scope_key)
        scope_key = _scope_key(write)
        for r in self.s.results:
            if (
                r.run_id == run_id
                and r.write.instrument_id == write.instrument_id
                and r.write.analysis_key == write.analysis_key
                and _scope_key(r.write) == scope_key
            ):
                r.write = write
                return r.id
        self.s._result_seq += 1
        rid = self.s._result_seq
        self.s.results.append(_StoredResult(id=rid, run_id=run_id, write=write))
        return rid

    def list_run_results(self, run_id, instrument_id):
        from app.db.repositories.protocols import RunAnalysisRow

        by_id = {r.id: r for r in self.s.results}
        out: list[RunAnalysisRow] = []
        for r in self.s.results:
            if r.run_id != run_id or r.write.instrument_id != instrument_id:
                continue
            payload = r.write.result or {}
            if r.write.carried and r.write.carried_from_result_id in by_id:
                payload = by_id[r.write.carried_from_result_id].write.result or {}
            out.append(
                RunAnalysisRow(
                    result_id=r.id,
                    analysis_key=r.write.analysis_key,
                    scope=r.write.scope,
                    timeframe=r.write.timeframe,
                    status=r.write.status,
                    values=payload.get("values", {}) or {},
                    aux=payload.get("aux", {}) or {},
                    meta=payload.get("meta", {}) or {},
                    warnings=list(payload.get("warnings", []) or []),
                )
            )
        return out

    def last_fingerprint(self, instrument_id, analysis_key, scope_key):
        from app.db.repositories.protocols import ResultFingerprint

        match = [
            r
            for r in self.s.results
            if r.write.instrument_id == instrument_id
            and r.write.analysis_key == analysis_key
            and _scope_key(r.write) == scope_key
        ]
        if not match:
            return None
        r = max(match, key=lambda x: x.id)
        by_id = {x.id: x for x in self.s.results}
        root, res = r, (r.write.result or {})
        seen = {r.id}
        while res.get("carried") and res.get("carried_from_result_id") in by_id:
            nxt = res["carried_from_result_id"]
            if nxt in seen:
                break
            seen.add(nxt)
            root = by_id[nxt]
            res = root.write.result or {}
        meta = res.get("meta", {})
        return ResultFingerprint(
            result_id=root.id,
            input_window_end=r.write.input_window_end,
            params_hash=r.write.params_hash,
            algo_version=r.write.algo_version,
            last_bar_final=bool(meta.get("last_bar_final", True)),
            summary={"values": res.get("values", {}), "aux": res.get("aux", {})},
        )


class MemoryScoreRepository:
    def __init__(self, store: MemoryStore) -> None:
        self.s = store

    def previous_composite(self, instrument_id, timeframe, before_run_id) -> float | None:
        prev: float | None = None
        for sc in self.s.scores:
            if (
                sc.write.instrument_id == instrument_id
                and sc.write.timeframe == timeframe
                and sc.run_id < before_run_id
            ):
                prev = sc.write.composite_score
        return prev

    def upsert_score(self, run_id: int, write: ScoreWrite) -> int:
        for sc in self.s.scores:
            if (
                sc.run_id == run_id
                and sc.write.instrument_id == write.instrument_id
                and sc.write.timeframe == write.timeframe
            ):
                sc.write = write
                self.s.factors[sc.id] = list(write.factors)
                return sc.id
        self.s._score_seq += 1
        sid = self.s._score_seq
        self.s.scores.append(_StoredScore(id=sid, run_id=run_id, write=write))
        self.s.factors[sid] = list(write.factors)
        return sid


class MemoryProjectionRepository:
    def __init__(self, store: MemoryStore) -> None:
        self.s = store

    def upsert_current_analysis(self, write: ResultWrite, analysis_result_id: int) -> None:
        key = (write.instrument_id, write.analysis_key, write.scope_ref())
        self.s.current_analysis[key] = {
            "analysis_result_id": analysis_result_id,
            "status": write.status,
            "as_of_ts": write.as_of_ts,
            "algo_version": write.algo_version,
            "params_hash": write.params_hash,
            "carried": write.carried,
            "summary": write.summary,
            "scope": write.scope,
            "timeframe": write.timeframe,
        }

    def upsert_current_score(self, write, signal_score_id, run_id, delta) -> None:
        key = (write.instrument_id, write.timeframe.value)
        self.s.current_scores[key] = {
            "signal_score_id": signal_score_id,
            "run_id": run_id,
            "composite_score": write.composite_score,
            "confidence": write.confidence,
            "raw_label": write.raw_label,
            "effective_label": write.effective_label,
            "low_confidence": write.low_confidence,
            "as_of_ts": write.as_of_ts,
            "delta_vs_previous": delta,
            "warnings": write.warnings,
        }

    def rebuild_projections(self) -> None:
        """Reproduce ``current_*`` purely from stored history (docs/03 §5.5)."""
        self.s.current_analysis.clear()
        self.s.current_scores.clear()
        # latest analysis_result per (instrument, key, scope_ref) by (run_id, id)
        by_key: dict[tuple[int, str, str], _StoredResult] = {}
        for r in sorted(self.s.results, key=lambda x: (x.run_id, x.id)):
            by_key[(r.write.instrument_id, r.write.analysis_key, r.write.scope_ref())] = r
        for r in by_key.values():
            self.upsert_current_analysis(r.write, r.id)
        # latest score per (instrument, timeframe)
        by_score: dict[tuple[int, str], _StoredScore] = {}
        for sc in sorted(self.s.scores, key=lambda x: (x.run_id, x.id)):
            by_score[(sc.write.instrument_id, sc.write.timeframe.value)] = sc
        for sc in by_score.values():
            prev = self.previous_or_none(sc)
            delta = None if prev is None else round(sc.write.composite_score - prev, 6)
            self.upsert_current_score(sc.write, sc.id, sc.run_id, delta)

    def previous_or_none(self, sc: _StoredScore) -> float | None:
        prev: float | None = None
        for other in sorted(self.s.scores, key=lambda x: (x.run_id, x.id)):
            if other.id == sc.id:
                break
            if (
                other.write.instrument_id == sc.write.instrument_id
                and other.write.timeframe == sc.write.timeframe
            ):
                prev = other.write.composite_score
        return prev


def _scope_key(w: ResultWrite) -> str:
    if w.scope is AnalysisScope.PER_TIMEFRAME:
        return f"PER_TIMEFRAME:{w.timeframe.value}"  # type: ignore[union-attr]
    if w.scope is AnalysisScope.SESSION:
        return f"SESSION:{w.session_date}"
    return f"SNAPSHOT:{w.snapshot_ts}"


def build_memory_repositories(
    tracked: list[InstrumentView] | None = None,
) -> tuple[Repositories, MemoryStore]:
    store = MemoryStore(tracked=tracked)
    repos = Repositories(
        runs=MemoryRunRepository(store),
        instruments=MemoryInstrumentRepository(store),
        analysis_results=MemoryAnalysisResultRepository(store),
        scores=MemoryScoreRepository(store),
        projections=MemoryProjectionRepository(store),
        market_data=MemoryMarketDataRepository(),
        market_profile=MemoryMarketProfileRepository(),
    )
    return repos, store
