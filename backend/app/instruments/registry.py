"""Canonical construction + idempotent sync (Phase 2.2, §4–§8).

``sync_instruments`` is deterministic and idempotent: the same records produce the
same canonical identities, the same ``contract_key`` values, no duplicate
contracts, no duplicate provider mappings. It never invents contracts, strike
ladders, expiries or underlyings (§6); a derivative whose underlying cannot be
resolved to an INDEX is quarantined (§5).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from analytical_core.enums import InstrumentType
from app.db.repositories.instrument_registry import (
    InstrumentRegistryRepository,
    RegistryIntegrityError,
)
from app.instruments.errors import RejectedRow
from app.instruments.validation import CanonicalInstrument, validate
from app.providers.base import InstrumentRecord


@dataclass(slots=True)
class SyncReport:
    provider: str
    rows_in_master: int
    accepted: int = 0
    created: int = 0
    updated: int = 0
    remapped: int = 0
    unchanged: int = 0
    deactivated: int = 0
    quarantined: list[RejectedRow] = field(default_factory=list)

    @property
    def persisted(self) -> int:
        return self.created + self.updated + self.remapped + self.unchanged

    def summary_line(self) -> str:
        return (
            f"provider={self.provider} rows_in_master={self.rows_in_master} "
            f"accepted={self.accepted} created={self.created} updated={self.updated} "
            f"remapped={self.remapped} unchanged={self.unchanged} "
            f"deactivated={self.deactivated} quarantined={len(self.quarantined)}"
        )


def _apply_map_action(report: SyncReport, inst_action: str, map_action: str) -> None:
    if map_action == "remapped":
        report.remapped += 1
    elif inst_action == "created":
        report.created += 1
    elif inst_action == "updated":
        report.updated += 1
    else:
        report.unchanged += 1


def sync_instruments(
    records: Iterable[InstrumentRecord],
    *,
    provider: str,
    repo: InstrumentRegistryRepository,
    extra_rejections: Iterable[RejectedRow] = (),
) -> SyncReport:
    records = list(records)
    report = SyncReport(provider=provider, rows_in_master=len(records))
    report.quarantined.extend(extra_rejections)

    accepted, quarantined = validate(records)
    report.quarantined.extend(quarantined)
    report.accepted = len(accepted)

    seen_ids: set[int] = set()

    def _persist(draft: CanonicalInstrument, underlying_id: int | None) -> None:
        # remap-collision pre-check (§8): the new provider_symbol must not already
        # belong to a *different* instrument.
        owner = repo.get_instrument_id_by_provider_symbol(provider, draft.provider_symbol)
        target = repo.get_instrument_by_contract_key(draft.contract_key)
        target_id = target.id if target else None
        if owner is not None and owner != target_id:
            report.quarantined.append(
                RejectedRow(
                    "resolve",
                    f"provider_symbol already mapped to instrument {owner}",
                    draft.provider_symbol,
                    draft.contract_key,
                    dict(draft.provider_metadata),
                )
            )
            return
        try:
            inst_id, inst_action = repo.upsert_instrument(draft, underlying_id=underlying_id)
        except RegistryIntegrityError as exc:
            report.quarantined.append(
                RejectedRow(
                    "resolve",
                    str(exc),
                    draft.provider_symbol,
                    draft.contract_key,
                    dict(draft.provider_metadata),
                )
            )
            return
        map_action = repo.upsert_provider_map(
            provider, inst_id, draft.provider_symbol, draft.provider_metadata
        )
        seen_ids.add(inst_id)
        _apply_map_action(report, inst_action, map_action)

    # --- Phase A: indices first (no underlying) -------------------------
    for draft in accepted:
        if draft.instrument_type is InstrumentType.INDEX:
            _persist(draft, None)

    # --- Phase B: derivatives (resolve underlying_id) -----------------
    for draft in accepted:
        if draft.instrument_type is InstrumentType.INDEX:
            continue
        assert draft.underlying_provider_key is not None  # ensured by validate()
        underlying_id = repo.get_instrument_id_by_provider_symbol(
            provider, draft.underlying_provider_key
        )
        if underlying_id is None:
            report.quarantined.append(
                RejectedRow(
                    "resolve",
                    f"unresolved underlying: {draft.underlying_provider_key}",
                    draft.provider_symbol,
                    draft.contract_key,
                    dict(draft.provider_metadata),
                )
            )
            continue
        existing = repo.get_instrument_by_contract_key(draft.contract_key)
        if existing is not None and existing.id == underlying_id:
            report.quarantined.append(
                RejectedRow(
                    "resolve",
                    "self-referential underlying",
                    draft.provider_symbol,
                    draft.contract_key,
                    dict(draft.provider_metadata),
                )
            )
            continue
        if repo.get_instrument_type(underlying_id) is not InstrumentType.INDEX:
            report.quarantined.append(
                RejectedRow(
                    "resolve",
                    f"underlying instrument {underlying_id} is not an INDEX",
                    draft.provider_symbol,
                    draft.contract_key,
                    dict(draft.provider_metadata),
                )
            )
            continue
        _persist(draft, underlying_id)

    # --- deactivate contracts absent from this master (§6) -----------
    known = repo.list_active_instrument_ids(provider)
    for absent_id in sorted(known - seen_ids):
        repo.deactivate(absent_id)
        report.deactivated += 1

    report.quarantined.sort(key=RejectedRow.sort_key)
    return report
