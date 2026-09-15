"""Astro per-day chart scalars (docs/13 §5).

Adds ``astro_days`` — one row per date with weekday, lagna (ascendant), Moon
nakshatra / rashi / pada, Sun rashi, tithi + paksha, sunrise/sunset. Denormalised
from ``astro_positions`` + the ephemeris so the astro x market study joins are
trivial. No enum types; PK is ``as_of_date``.

Revision ID: 0003_astro_days
Revises: 0002_astro_tables
Create Date: 2026-08-30
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003_astro_days"
down_revision = "0002_astro_tables"
branch_labels = None
depends_on = None

_TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "astro_days",
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("as_of_ts", _TS, nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("day_name", sa.String(length=9), nullable=False),
        sa.Column("weekday_lord", sa.String(length=8), nullable=False),
        sa.Column("lagna_longitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("lagna_rashi_index", sa.Integer(), nullable=False),
        sa.Column("lagna_rashi", sa.String(length=16), nullable=False),
        sa.Column("lagna_nakshatra_index", sa.Integer(), nullable=False),
        sa.Column("lagna_nakshatra", sa.String(length=24), nullable=False),
        sa.Column("lagna_pada", sa.Integer(), nullable=False),
        sa.Column("moon_rashi_index", sa.Integer(), nullable=False),
        sa.Column("moon_rashi", sa.String(length=16), nullable=False),
        sa.Column("moon_nakshatra_index", sa.Integer(), nullable=False),
        sa.Column("moon_nakshatra", sa.String(length=24), nullable=False),
        sa.Column("moon_pada", sa.Integer(), nullable=False),
        sa.Column("moon_nakshatra_lord", sa.String(length=8), nullable=False),
        sa.Column("sun_rashi_index", sa.Integer(), nullable=False),
        sa.Column("sun_rashi", sa.String(length=16), nullable=False),
        sa.Column("tithi", sa.Integer(), nullable=False),
        sa.Column("paksha", sa.String(length=8), nullable=False),
        sa.Column("sunrise_ts", _TS, nullable=False),
        sa.Column("sunset_ts", _TS, nullable=False),
        sa.Column("ayanamsha", sa.Numeric(9, 6), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("created_at", _TS, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("as_of_date", name="pk_astro_days"),
        sa.CheckConstraint("tithi BETWEEN 1 AND 30", name="ck_astro_days_tithi_range"),
    )
    op.create_index("ix_astro_days_weekday", "astro_days", ["weekday"])
    op.create_index("ix_astro_days_moon_nakshatra_index", "astro_days", ["moon_nakshatra_index"])
    op.create_index("ix_astro_days_lagna_rashi_index", "astro_days", ["lagna_rashi_index"])


def downgrade() -> None:
    op.drop_index("ix_astro_days_lagna_rashi_index", table_name="astro_days")
    op.drop_index("ix_astro_days_moon_nakshatra_index", table_name="astro_days")
    op.drop_index("ix_astro_days_weekday", table_name="astro_days")
    op.drop_table("astro_days")
