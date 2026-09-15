"""Index-constituent weights table (docs/15).

Adds ``index_weights`` — seeded, owner-maintained free-float weights for an
index's constituents (one row per index_key + symbol + effective_date). No enum
types, no FKs (constituents are not tracked instruments).

``0001_phase1_baseline`` builds the baseline with ``Base.metadata.create_all``
against the *current* models, so on a fresh DB the table already exists — hence
``IF NOT EXISTS``, which makes this a no-op on a fresh DB and additive on a
pre-existing one.

Revision ID: 0005_index_weights
Revises: 0004_mp_events
Create Date: 2026-09-03
"""

from __future__ import annotations

from alembic import op

revision = "0005_index_weights"
down_revision = "0004_mp_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS index_weights (
            id               BIGSERIAL PRIMARY KEY,
            index_key        VARCHAR(32)  NOT NULL,
            effective_date   DATE         NOT NULL,
            symbol           VARCHAR(32)  NOT NULL,
            name             VARCHAR(96)  NOT NULL,
            sector           VARCHAR(48)  NOT NULL,
            weight_pct       NUMERIC(9, 6) NOT NULL,
            provider         VARCHAR(24),
            provider_symbol  VARCHAR(64),
            source           TEXT         NOT NULL DEFAULT 'seed',
            created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT index_weights_identity UNIQUE (index_key, symbol, effective_date)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_index_weights_lookup "
        "ON index_weights (index_key, effective_date)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS index_weights")
