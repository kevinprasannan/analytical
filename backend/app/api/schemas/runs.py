"""Run / cycle models (docs/07 §4.6)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from analytical_core.enums import (
    PhaseStatus,
    RunPhase,
    RunStatus,
    RunTrigger,
)


class RunSummary(BaseModel):
    id: int
    cycle_seq: int
    trigger: RunTrigger
    status: RunStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    algo_version: str
    scoring_version: str
    phase_counts: dict[str, dict[str, int]] = Field(default_factory=dict)


class PhaseStatusItem(BaseModel):
    phase: RunPhase
    status: PhaseStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    detail: dict[str, Any] = Field(default_factory=dict)


class InstrumentStatusItem(BaseModel):
    instrument_id: int
    phase: RunPhase
    outcome: str


class RunDetail(RunSummary):
    phases_requested: list[str] = Field(default_factory=list)
    phase_status: list[PhaseStatusItem] = Field(default_factory=list)
    instrument_status: list[InstrumentStatusItem] = Field(default_factory=list)
    config_snapshot: dict[str, Any] = Field(default_factory=dict)
    params_hash: str


class RunTriggerRequest(BaseModel):
    trigger: RunTrigger = RunTrigger.MANUAL
    phases: list[RunPhase] = Field(
        default_factory=lambda: [RunPhase.INGEST, RunPhase.ANALYZE, RunPhase.SCORE]
    )
