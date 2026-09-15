"""Read the flat ``app_settings`` key/value store (docs/03 §5.1).

The worker loads this once per cycle and hands it to the engines so
``PATCH /config`` edits take effect from the next cycle.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m


def load_app_settings(session: Session) -> dict[str, Any]:
    return {r.key: r.value for r in session.execute(select(m.AppSetting)).scalars()}
