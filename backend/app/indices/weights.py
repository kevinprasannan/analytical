"""Load / read the seeded ``index_weights`` table (docs/15)."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from analytical_core.indices import WeightRow
from app.db import models as m

DEFAULT_WEIGHTS_CSV = Path(__file__).resolve().parents[2] / "data" / "nifty50_weights.csv"

#: index contract_key -> the human name the constituent view reports
INDEX_NAMES: dict[str, str] = {
    "NIFTY-INDEX": "NIFTY 50",
    "BANKNIFTY-INDEX": "NIFTY Bank",
    "SENSEX-INDEX": "BSE SENSEX",
}


def load_weights_csv(
    session: Session,
    path: str | Path,
    *,
    index_key: str = "NIFTY-INDEX",
    effective_date: date,
    provider: str | None = None,
    replace: bool = True,
) -> int:
    """Load a constituent factsheet CSV into ``index_weights`` for one
    ``(index_key, effective_date)``. Columns: ``symbol,name,sector,weight_pct``
    and an optional ``provider_symbol``; ``#`` / blank lines are skipped.
    ``replace`` clears any existing rows for that key+date first. Returns the
    row count loaded."""
    rows: list[dict] = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(r for r in fh if r.strip() and not r.lstrip().startswith("#"))
        for r in reader:
            sym = (r.get("symbol") or "").strip().upper()
            if not sym:
                continue
            rows.append(
                {
                    "index_key": index_key,
                    "effective_date": effective_date,
                    "symbol": sym,
                    "name": (r.get("name") or sym).strip(),
                    "sector": (r.get("sector") or "Unclassified").strip(),
                    "weight_pct": float(r["weight_pct"]),
                    "provider": provider,
                    "provider_symbol": (r.get("provider_symbol") or "").strip() or None,
                    "source": "seed",
                }
            )
    if not rows:
        raise ValueError(f"no constituent rows in {path}")

    if replace:
        session.execute(
            delete(m.IndexWeight).where(
                m.IndexWeight.index_key == index_key,
                m.IndexWeight.effective_date == effective_date,
            )
        )
    session.execute(m.IndexWeight.__table__.insert(), rows)
    return len(rows)


def latest_effective_date(session: Session, index_key: str) -> date | None:
    try:
        return session.execute(
            select(m.IndexWeight.effective_date)
            .where(m.IndexWeight.index_key == index_key)
            .order_by(m.IndexWeight.effective_date.desc())
            .limit(1)
        ).scalar()
    except SQLAlchemyError:  # table not migrated yet — treat as "nothing seeded"
        session.rollback()
        return None


def weight_rows_for(
    session: Session, index_key: str, *, effective_date: date | None = None
) -> tuple[list[WeightRow], date | None, dict[str, str | None]]:
    """The constituent weight rows for ``index_key`` at ``effective_date``
    (default: the latest loaded). Returns ``(rows, effective_date,
    {symbol: provider_symbol})``. ``rows`` is empty when nothing is seeded."""
    eff = effective_date or latest_effective_date(session, index_key)
    if eff is None:
        return [], None, {}
    recs = list(
        session.execute(
            select(m.IndexWeight).where(
                m.IndexWeight.index_key == index_key,
                m.IndexWeight.effective_date == eff,
            )
        ).scalars()
    )
    rows = [
        WeightRow(symbol=r.symbol, name=r.name, sector=r.sector, weight_pct=float(r.weight_pct))
        for r in recs
    ]
    provider_symbols = {r.symbol: r.provider_symbol for r in recs}
    return rows, eff, provider_symbols
