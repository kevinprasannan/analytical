"""Index-constituent weightage — seeded reference data + read helpers (docs/15).

The pure analytics live in ``analytical_core.indices``; this package owns the
``index_weights`` table: loading the owner-maintained factsheet CSV and reading
the latest effective set for an index.
"""

from __future__ import annotations

from app.indices.weights import (
    DEFAULT_WEIGHTS_CSV,
    latest_effective_date,
    load_weights_csv,
    weight_rows_for,
)

__all__ = [
    "DEFAULT_WEIGHTS_CSV",
    "latest_effective_date",
    "load_weights_csv",
    "weight_rows_for",
]
