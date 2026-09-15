"""``analytical-index-weights`` - load / inspect seeded index constituent weights (docs/15).

    analytical-index-weights load data/nifty50_weights.csv --effective-date 2026-07-31
    analytical-index-weights load fs.csv --index BANKNIFTY-INDEX --effective-date 2026-07-31
    analytical-index-weights show                      # latest NIFTY-INDEX set
    analytical-index-weights show --index NIFTY-INDEX --date 2026-07-31
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from app.config import get_settings
from app.db.session import session_scope
from app.indices.weights import (
    DEFAULT_WEIGHTS_CSV,
    latest_effective_date,
    load_weights_csv,
    weight_rows_for,
)


def _cmd_load(args: argparse.Namespace) -> int:
    eff = date.fromisoformat(args.effective_date)
    path = args.csv or str(DEFAULT_WEIGHTS_CSV)
    with session_scope(get_settings()) as session:
        n = load_weights_csv(
            session,
            path,
            index_key=args.index,
            effective_date=eff,
            provider=args.provider,
            replace=not args.append,
        )
        session.flush()
        rows, _, _ = weight_rows_for(session, args.index, effective_date=eff)
        total = sum(r.weight_pct for r in rows)
    sys.stdout.write(
        f"loaded {n} constituents for {args.index} @ {eff}  (sum weight = {total:.2f}%)\n"
    )
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    eff = date.fromisoformat(args.date) if args.date else None
    with session_scope(get_settings()) as session:
        if eff is None:
            eff = latest_effective_date(session, args.index)
        if eff is None:
            sys.stdout.write(f"no weights loaded for {args.index}\n")
            return 1
        rows, eff, prov = weight_rows_for(session, args.index, effective_date=eff)
    rows.sort(key=lambda r: -r.weight_pct)
    total = sum(r.weight_pct for r in rows)
    sys.stdout.write(f"{args.index} @ {eff}  -  {len(rows)} names, sum = {total:.2f}%\n")
    cum = 0.0
    for i, r in enumerate(rows, start=1):
        cum += r.weight_pct
        pv = prov.get(r.symbol) or "-"
        sys.stdout.write(
            f"  {i:>2}. {r.symbol:<12} {r.weight_pct:6.3f}%  cum {cum:6.2f}%  "
            f"{r.sector:<28} {pv}\n"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="analytical-index-weights", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    lo = sub.add_parser("load", help="load a constituent factsheet CSV")
    lo.add_argument("csv", nargs="?", help=f"CSV path (default: {DEFAULT_WEIGHTS_CSV})")
    lo.add_argument("--index", default="NIFTY-INDEX", help="index contract_key")
    lo.add_argument("--effective-date", required=True, help="rebalance date, ISO")
    lo.add_argument("--provider", default=None, help="tag rows with this provider")
    lo.add_argument("--append", action="store_true", help="keep existing rows for that date")
    lo.set_defaults(fn=_cmd_load)

    sh = sub.add_parser("show", help="print the loaded weights")
    sh.add_argument("--index", default="NIFTY-INDEX")
    sh.add_argument("--date", default=None, help="effective date, ISO (default: latest)")
    sh.set_defaults(fn=_cmd_show)

    args = p.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
