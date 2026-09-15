"""Phase 1 baseline schema (docs/03 §5).

Creates all Phase-1 tables and their native PG enum types from
``app.db.models`` — which are authored to match those models exactly (no
autogenerate, per CLAUDE.md hard rule).

Enum types: created by ``metadata.create_all`` via ``pg_enum(... values_callable
=...)``, so every label comes from ``analytical_core.enums`` (docs/12 single
source of truth). ``analytical_core.enums.emit_sql()`` renders the same list for
inspection and is checked against the models by ``test_enum_contract``.

Revision ID: 0001_phase1_baseline
Revises:
Create Date: 2026-08-27
"""

from __future__ import annotations

from alembic import op
from app.db import models as _models  # noqa: F401  (populates Base.metadata)
from app.db.base import Base

revision = "0001_phase1_baseline"
down_revision = None
branch_labels = None
depends_on = None


# Tables owned by this baseline = everything except side tables added by later
# migrations (astro_* -> 0002). Scoping `upgrade` keeps a fresh `upgrade head`
# from pre-creating 0002's tables (and keeps `--sql` from emitting them twice).
# `downgrade` stays unscoped: by the time it runs, 0002's downgrade has already
# dropped the astro tables, so an unfiltered drop_all cleans the rest + all the
# native ENUM types in the correct order.
_BASELINE_TABLES = [t for t in Base.metadata.sorted_tables if not t.name.startswith("astro_")]


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), tables=_BASELINE_TABLES)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
