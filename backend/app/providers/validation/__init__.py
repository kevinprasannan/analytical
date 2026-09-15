"""Machine-readable provider-validation gate (docs/11 §0).

The authoritative status file is ``docs/11-provider-validation.status.yaml``.
This package parses it, validates its schema/statuses, and evaluates the gate.
It **never** modifies the file.

Public surface:
  * ``ALLOWED_PV_STATUS``           — contract-controlled status vocabulary
  * ``load_status(path)``           — parse + schema validate
  * ``evaluate(status, ...)``       — gate decision (blocked / open items / errors)
  * ``gate.main(argv)``             — CLI (`analytical-gate`), exit != 0 when blocked
"""

from app.providers.validation.gate import GateResult, evaluate, render
from app.providers.validation.loader import ValidationSchemaError, load_status
from app.providers.validation.status import ALLOWED_PV_STATUS, PVItem, ValidationStatusFile

__all__ = [
    "ALLOWED_PV_STATUS",
    "GateResult",
    "PVItem",
    "ValidationSchemaError",
    "ValidationStatusFile",
    "evaluate",
    "load_status",
    "render",
]
