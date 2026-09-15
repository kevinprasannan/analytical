"""Deterministic rejection record shared across the instrument-registry layers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class RejectedRow:
    """A provider master row that did not enter the canonical registry.

    ``stage`` is one of ``"normalise" | "validate" | "resolve"``. ``reason`` is a
    stable, human-readable explanation (no timestamps / ids that would make it
    non-deterministic).
    """

    stage: str
    reason: str
    provider_symbol: str | None = None
    contract_key: str | None = None
    raw: Mapping[str, object] = field(default_factory=dict)

    def sort_key(self) -> tuple[str, str, str]:
        return (self.contract_key or "", self.provider_symbol or "", self.reason)
