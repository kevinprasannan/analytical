"""Parse + schema-validate the PV status YAML. Read-only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.providers.validation.status import (
    ALLOWED_PV_STATUS,
    PV_IDS,
    PVItem,
    ValidationStatusFile,
)

_REQUIRED_ITEM_KEYS = {
    "id",
    "title",
    "requirement",
    "status",
    "blocks_phase_2",
    "evidence",
    "fallback_ref",
    "impact",
    "notes",
}


class ValidationSchemaError(ValueError):
    """The status file is missing, malformed, or uses an unknown status value."""


def load_status(path: str | Path) -> ValidationStatusFile:
    p = Path(path)
    if not p.is_file():
        raise ValidationSchemaError(f"status file not found: {p}")
    try:
        raw: Any = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - defensive
        raise ValidationSchemaError(f"invalid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValidationSchemaError("top level must be a mapping")

    meta = raw.get("meta")
    if not isinstance(meta, dict):
        raise ValidationSchemaError("missing 'meta' mapping")
    schema_version = meta.get("schema_version")
    if not isinstance(schema_version, int):
        raise ValidationSchemaError("meta.schema_version must be an integer")
    gate_blocking_ids = meta.get("gate_blocking_ids")
    if not isinstance(gate_blocking_ids, list) or not all(
        isinstance(x, str) for x in gate_blocking_ids
    ):
        raise ValidationSchemaError("meta.gate_blocking_ids must be a list of strings")

    items_raw = raw.get("items")
    if not isinstance(items_raw, dict):
        raise ValidationSchemaError("missing 'items' mapping")

    items: dict[str, PVItem] = {}
    for pv_id in PV_IDS:
        if pv_id not in items_raw:
            raise ValidationSchemaError(f"items is missing {pv_id}")
        items[pv_id] = _parse_item(pv_id, items_raw[pv_id])

    unknown = set(items_raw) - set(PV_IDS)
    if unknown:
        raise ValidationSchemaError(f"unknown item ids: {sorted(unknown)}")

    return ValidationStatusFile(
        schema_version=schema_version,
        gate_blocking_ids=tuple(gate_blocking_ids),
        items=items,
    )


def _parse_item(pv_id: str, node: Any) -> PVItem:
    if not isinstance(node, dict):
        raise ValidationSchemaError(f"{pv_id} must be a mapping")
    missing = _REQUIRED_ITEM_KEYS - set(node)
    if missing:
        raise ValidationSchemaError(f"{pv_id} missing keys: {sorted(missing)}")

    declared_id = node.get("id")
    if declared_id != pv_id:
        raise ValidationSchemaError(f"{pv_id}: 'id' field is {declared_id!r}")

    status = node["status"]
    if status not in ALLOWED_PV_STATUS:
        raise ValidationSchemaError(f"{pv_id}: status {status!r} not in {ALLOWED_PV_STATUS}")

    blocks = node["blocks_phase_2"]
    if not isinstance(blocks, bool):
        raise ValidationSchemaError(f"{pv_id}: blocks_phase_2 must be a boolean")

    evidence_raw = node.get("evidence")
    if evidence_raw is None:
        evidence: tuple[str, ...] = ()
    elif isinstance(evidence_raw, list) and all(isinstance(x, str) for x in evidence_raw):
        evidence = tuple(evidence_raw)
    else:
        raise ValidationSchemaError(f"{pv_id}: evidence must be null or a list of strings")

    return PVItem(
        id=pv_id,
        title=str(node["title"]),
        requirement=str(node["requirement"]),
        status=status,
        blocks_phase_2=blocks,
        evidence=evidence,
        fallback_ref=_opt_str(node.get("fallback_ref")),
        impact=str(node["impact"]),
        notes=_opt_str(node.get("notes")),
        branch=_opt_str(node.get("branch")),
        decided_on=_opt_str(node.get("decided_on")),
    )


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
