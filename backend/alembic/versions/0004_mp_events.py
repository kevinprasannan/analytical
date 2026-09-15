"""Market Profile event layer columns (docs/14 §14.9 slice 3).

Adds three columns to ``market_profile_sessions``:
  * ``close``              — session close price (the profile builder already
                             computes it; needed as a prior-session reference).
  * ``events``             — compact ``event_result_to_dict`` blob from
                             ``analytical_core.market_profile.events``.
  * ``mp_events_version``  — the ``MP_EVENTS_VERSION`` that produced ``events``.

No new table, no enum types.

``0001_phase1_baseline`` builds the baseline tables with
``Base.metadata.create_all`` against the *current* models, so on a fresh DB
``market_profile_sessions`` is already created with these columns — hence the
``IF NOT EXISTS`` / ``IF EXISTS`` guards, which make this migration a no-op on a
fresh DB and additive on a pre-existing one.

Revision ID: 0004_mp_events
Revises: 0003_astro_days
Create Date: 2026-08-31
"""

from __future__ import annotations

from alembic import op

revision = "0004_mp_events"
down_revision = "0003_astro_days"
branch_labels = None
depends_on = None


_T = "ALTER TABLE market_profile_sessions "


def upgrade() -> None:
    op.execute(_T + "ADD COLUMN IF NOT EXISTS close NUMERIC(18, 4)")
    op.execute(_T + "ADD COLUMN IF NOT EXISTS events JSONB")
    op.execute(_T + "ADD COLUMN IF NOT EXISTS mp_events_version TEXT")


def downgrade() -> None:
    op.execute(_T + "DROP COLUMN IF EXISTS mp_events_version")
    op.execute(_T + "DROP COLUMN IF EXISTS events")
    op.execute(_T + "DROP COLUMN IF EXISTS close")
