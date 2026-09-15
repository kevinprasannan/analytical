"""Typed representation of ``docs/11-provider-validation.status.yaml``.

The status vocabulary is contract-controlled: exactly the three strings in
``ALLOWED_PV_STATUS``. It is intentionally NOT in ``analytical_core.enums`` — it
is never stored in the database or exposed as an API contract enum; it governs a
build/runtime gate only (documented Phase-1 choice).
"""

from __future__ import annotations

from dataclasses import dataclass

#: Contract-controlled status vocabulary (docs/11 §0).
ALLOWED_PV_STATUS: tuple[str, ...] = ("OPEN", "CONFIRMED", "ACCEPTED_FALLBACK")

#: The eight PV requirement ids (docs/11 §1).
PV_IDS: tuple[str, ...] = tuple(f"PV-{n}" for n in range(1, 9))

#: PV ids whose ``OPEN`` state blocks Phase 2 (docs/11 §0). PV-8 is exempt.
DEFAULT_BLOCKING_IDS: tuple[str, ...] = tuple(f"PV-{n}" for n in range(1, 8))

#: PV ids that must record a design ``branch`` once resolved, with the allowed set.
BRANCH_REQUIRED: dict[str, frozenset[str]] = {
    "PV-2": frozenset({"NATIVE", "AGGREGATE_FROM_M1"}),
    "PV-4": frozenset({"A_PER_CANDLE", "B_SNAPSHOT"}),
}


@dataclass(frozen=True, slots=True)
class PVItem:
    id: str
    title: str
    requirement: str
    status: str
    blocks_phase_2: bool
    evidence: tuple[str, ...]
    fallback_ref: str | None
    impact: str
    notes: str | None
    branch: str | None
    decided_on: str | None

    @property
    def is_open(self) -> bool:
        return self.status == "OPEN"

    @property
    def is_resolved(self) -> bool:
        return self.status in ("CONFIRMED", "ACCEPTED_FALLBACK")


@dataclass(frozen=True, slots=True)
class ValidationStatusFile:
    schema_version: int
    gate_blocking_ids: tuple[str, ...]
    items: dict[str, PVItem]

    def blocking_items(self) -> list[PVItem]:
        return [self.items[i] for i in self.gate_blocking_ids if i in self.items]

    def open_blocking_ids(self) -> list[str]:
        return [it.id for it in self.blocking_items() if it.is_open]
