"""Shared phase-result types for the worker pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field

from analytical_core.enums import InstrumentPhaseOutcome, PhaseStatus, RunPhase


@dataclass(slots=True)
class PhaseOutcome:
    phase: RunPhase
    status: PhaseStatus
    counts: dict[str, int] = field(default_factory=dict)
    instrument_outcomes: dict[int, InstrumentPhaseOutcome] = field(default_factory=dict)
    detail: dict = field(default_factory=dict)

    def record(self, instrument_id: int, outcome: InstrumentPhaseOutcome) -> None:
        self.instrument_outcomes[instrument_id] = outcome
        self.counts[outcome.value] = self.counts.get(outcome.value, 0) + 1

    def eligible_ids(self) -> set[int]:
        """Instruments fit to continue to the next phase (OK or DEGRADED)."""
        return {
            iid
            for iid, o in self.instrument_outcomes.items()
            if o in (InstrumentPhaseOutcome.OK, InstrumentPhaseOutcome.DEGRADED)
        }
