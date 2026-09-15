"""Analysis result envelope (docs/04 §3.2) + the no-engine result factory.

Most analyses are computed by :mod:`analytical_core.indicators` /
:mod:`analytical_core.market_profile`. When the applicability matrix (docs/04 §4)
says an analysis does not apply to an instrument type, or cannot run for lack of
data, the orchestrator still writes an ``analysis_results`` row — with the right
status, a human reason, and full provenance — via :func:`matrix_status_result`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from analytical_core.enums import AnalysisScope, AnalysisStatus
from analytical_core.params import params_hash, params_id
from analytical_core.versioning import ALGO_VERSION


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    analysis_key: str
    scope: AnalysisScope
    status: AnalysisStatus
    as_of_ts: datetime
    values: dict[str, Any] = field(default_factory=dict)
    aux: dict[str, Any] = field(default_factory=dict)
    series: dict[str, Any] | None = None
    warnings: tuple[str, ...] = ()
    meta: dict[str, Any] = field(default_factory=dict)


_DEFAULT_REASON = {
    AnalysisStatus.NOT_APPLICABLE: "analysis does not apply to this instrument type",
    AnalysisStatus.INSUFFICIENT_DATA: "insufficient data for this analysis",
}


def matrix_status_result(
    *,
    analysis_key: str,
    scope: AnalysisScope,
    as_of_ts: datetime,
    status: AnalysisStatus = AnalysisStatus.OK,
    reason: str | None = None,
    effective_params: dict[str, Any] | None = None,
) -> AnalysisResult:
    """A computed-nothing result: applicability-matrix ``NOT_APPLICABLE`` /
    ``INSUFFICIENT_DATA`` (or a bare ``OK`` when no engine is wired). Carries the
    same provenance (`algo_version`, `params_id`, `params_hash`) as a real result
    so downstream provenance checks are uniform (review M19)."""
    params = effective_params or {analysis_key: True}
    meta = {
        "algo_version": ALGO_VERSION,
        "params_id": params_id(analysis_key),
        "params_hash": params_hash(params),
    }
    if status is AnalysisStatus.OK:
        return AnalysisResult(
            analysis_key=analysis_key,
            scope=scope,
            status=status,
            as_of_ts=as_of_ts,
            values={},
            meta=meta,
        )
    detail = reason or _DEFAULT_REASON.get(status, status.value)
    return AnalysisResult(
        analysis_key=analysis_key,
        scope=scope,
        status=status,
        as_of_ts=as_of_ts,
        values={"reason": detail},
        warnings=(f"{analysis_key} {status.value}: {detail}",),
        meta=meta,
    )
