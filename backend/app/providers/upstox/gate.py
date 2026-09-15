"""Startup guard: refuse to construct/operate the Upstox adapter while the
provider-validation gate (docs/11) is not cleared (docs/02 §3.2).

Reads the machine-readable status file via ``app.providers.validation`` and
raises ``ProviderValidationGateError`` if any blocking PV item is OPEN or the
file is invalid. Never writes.
"""

from __future__ import annotations

from pathlib import Path

from app.providers.base import ProviderValidationGateError
from app.providers.validation import evaluate, load_status
from app.providers.validation.loader import ValidationSchemaError


def _status_path() -> Path:
    # backend/app/providers/upstox/gate.py -> repo root
    return Path(__file__).resolve().parents[4] / "docs" / "11-provider-validation.status.yaml"


def assert_gate_clear(status_path: str | Path | None = None) -> None:
    path = Path(status_path) if status_path else _status_path()
    try:
        status = load_status(path)
    except ValidationSchemaError as exc:
        raise ProviderValidationGateError(
            f"provider-validation status file invalid ({path}): {exc}"
        ) from exc
    result = evaluate(status)
    if result.blocked:
        raise ProviderValidationGateError(
            "Upstox adapter is disabled: provider-validation gate is BLOCKED. "
            f"OPEN items: {result.open_items or '-'}; errors: {result.errors or '-'}. "
            "Resolve docs/11-provider-validation.status.yaml before Phase 2."
        )
