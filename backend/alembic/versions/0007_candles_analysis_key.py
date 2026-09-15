"""Allow the ``candles`` analysis key (docs/05 §9b, docs/12).

Widens the ``analysis_results.analysis_key_known`` CHECK (real name, via the
metadata naming convention: ``ck_analysis_results_analysis_key_known``) to
accept ``candles``. Constraint-only DDL — no rows are read, updated, or deleted.
A fresh ``0001`` build already has the full list, so this is a no-op there.

Revision ID: 0007_candles_analysis_key
Revises: 0006_order_block_analysis_key
Create Date: 2026-09-08
"""

from __future__ import annotations

from alembic import op

from analytical_core.enums import ANALYSIS_KEY_CHECK_VALUES

revision = "0007_candles_analysis_key"
down_revision = "0006_order_block_analysis_key"
branch_labels = None
depends_on = None

_CK = "ck_analysis_results_analysis_key_known"
_IN = ", ".join(f"'{v}'" for v in ANALYSIS_KEY_CHECK_VALUES)
_PRIOR = ", ".join(
    f"'{v}'"
    for v in (
        "rsi",
        "bollinger",
        "ema7",
        "golden_cross",
        "volume",
        "open_interest",
        "market_profile",
        "order_block",
    )
)


def upgrade() -> None:
    op.execute(f"ALTER TABLE analysis_results DROP CONSTRAINT IF EXISTS {_CK}")
    op.execute(
        f"ALTER TABLE analysis_results ADD CONSTRAINT {_CK} CHECK (analysis_key IN ({_IN}))"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE analysis_results DROP CONSTRAINT IF EXISTS {_CK}")
    op.execute(
        f"ALTER TABLE analysis_results ADD CONSTRAINT {_CK} CHECK (analysis_key IN ({_PRIOR}))"
    )
