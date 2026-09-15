"""Create ONLY the new ``index_weights`` table (docs/15) on the configured DB.

Scoped and non-destructive: it creates that one table + its own unique
constraint and lookup index, and only if they do not already exist
(``checkfirst=True``). It never touches, drops, or alters any other table, and
never runs the alembic history — a later ``alembic upgrade head`` still works
because migration ``0005`` is ``CREATE TABLE IF NOT EXISTS``.

    python -m scripts.create_index_weights
"""

from __future__ import annotations

import sys

from sqlalchemy import inspect

from app.db import models as m
from app.db.session import get_engine


def main() -> int:
    engine = get_engine()
    insp = inspect(engine)
    existed = insp.has_table(m.IndexWeight.__tablename__)
    m.IndexWeight.__table__.create(bind=engine, checkfirst=True)
    with engine.connect() as conn:
        n = conn.exec_driver_sql("SELECT count(*) FROM index_weights").scalar()
    verb = "already present" if existed else "created"
    sys.stdout.write(
        f"index_weights {verb} on {engine.url.render_as_string(hide_password=True)} "
        f"({n} rows). No other table touched.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
