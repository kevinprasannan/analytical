"""Operational commands referenced by docs/10 Phase 1.

  * ``rebuild-projections`` — recompute ``current_*`` from history (docs/03 §5.5)
  * ``refresh-calendar``    — extend ``market_calendar`` further into the future
"""

from __future__ import annotations

import sys

from app.db.repositories.sqlalchemy import build_sqlalchemy_repositories
from app.db.seed import seed_calendar
from app.db.session import session_scope


def rebuild_projections() -> None:
    with session_scope() as db:
        build_sqlalchemy_repositories(db).projections.rebuild_projections()
    sys.stdout.write("rebuild-projections: done\n")


def refresh_calendar(years_ahead: int = 2) -> None:
    with session_scope() as db:
        n = seed_calendar(db, years_ahead=years_ahead)
    sys.stdout.write(f"refresh-calendar: ensured {n} calendar days\n")


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="analytical-db")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("rebuild-projections")
    rc = sub.add_parser("refresh-calendar")
    rc.add_argument("--years-ahead", type=int, default=2)
    args = parser.parse_args(argv)
    if args.cmd == "rebuild-projections":
        rebuild_projections()
    else:
        refresh_calendar(args.years_ahead)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
