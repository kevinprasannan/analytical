"""Allow the ``order_block`` analysis key (docs/05 §9a, docs/12).

``analysis_results.analysis_key`` is ``text`` + a CHECK (``analysis_key_known``)
listing the known ``AnalysisKey`` values. Adding ``order_block`` to the enum
means an existing DB's CHECK must be widened; a fresh ``0001`` build already has
it (the constraint is created from the current models), so this migration
rebuilds the constraint from the current enum list and is a harmless no-op on a
fresh DB.

Revision ID: 0006_order_block_analysis_key
Revises: 0005_index_weights
Create Date: 2026-09-07
"""

from __future__ import annotations

from alembic import op

from analytical_core.enums import ANALYSIS_KEY_CHECK_VALUES

revision = "0006_order_block_analysis_key"
down_revision = "0005_index_weights"
branch_labels = None
depends_on = None

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
    )
)


# SQLAlchemy's metadata naming_convention prefixes CHECK names as
# ck_<table>_<name>, so the live constraint is ck_analysis_results_analysis_key_known.
_CK = "ck_analysis_results_analysis_key_known"


def upgrade() -> None:
    op.execute(f"ALTER TABLE analysis_results DROP CONSTRAINT IF EXISTS {_CK}")
    op.execute(f"ALTER TABLE analysis_results DROP CONSTRAINT IF EXISTS analysis_key_known")
    op.execute(
        f"ALTER TABLE analysis_results ADD CONSTRAINT {_CK} CHECK (analysis_key IN ({_IN}))"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE analysis_results DROP CONSTRAINT IF EXISTS {_CK}")
    op.execute(
        f"ALTER TABLE analysis_results ADD CONSTRAINT {_CK} CHECK (analysis_key IN ({_PRIOR}))"
    )
