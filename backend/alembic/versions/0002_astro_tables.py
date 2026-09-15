"""Astro cross-check side tables (docs/13).

Adds ``astro_positions`` and ``astro_shadbala`` — sidereal (Lahiri) planetary
positions and classical Parashari Shadbala, one row per (date, body). No FK into
the market schema; joined to market data by calendar date. No new enum types
(``body`` / ``graha`` are TEXT + CHECK).

``upgrade`` uses ``create_all`` scoped to the two tables (kept 1:1 with the ORM
models); ``downgrade`` uses explicit ``op.drop_table`` — ``metadata.drop_all``
with a ``tables`` subset still fires the baseline's native-ENUM drop DDL.

Revision ID: 0002_astro_tables
Revises: 0001_phase1_baseline
Create Date: 2026-08-30
"""

from __future__ import annotations

from alembic import op
from app.db import models as _models
from app.db.base import Base

revision = "0002_astro_tables"
down_revision = "0001_phase1_baseline"
branch_labels = None
depends_on = None

_TABLES = [_models.AstroPosition.__table__, _models.AstroShadbala.__table__]


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), tables=_TABLES)


def downgrade() -> None:
    op.drop_index("ix_astro_shadbala_as_of_date", table_name="astro_shadbala")
    op.drop_table("astro_shadbala")
    op.drop_index("ix_astro_positions_as_of_date", table_name="astro_positions")
    op.drop_table("astro_positions")
