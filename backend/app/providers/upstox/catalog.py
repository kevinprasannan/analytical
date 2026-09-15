"""Search the Upstox instrument master(s) — the add-instrument autosuggest source.

Reads every ``*.json`` / ``*.json.gz`` in ``upstox_master_dir``, caches the
parsed rows per file (invalidated on mtime), and does a case-insensitive
substring match on the instrument key / name / trading symbol. Read-only; no
network.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from analytical_core.enums import InstrumentType, OptionType

_TYPE: dict[str, InstrumentType] = {
    "INDEX": InstrumentType.INDEX,
    "FUT": InstrumentType.FUTURE,
    "CE": InstrumentType.OPTION,
    "PE": InstrumentType.OPTION,
}
_SEG = {
    InstrumentType.INDEX: "INDEX",
    InstrumentType.FUTURE: "FUT",
    InstrumentType.OPTION: "OPT",
}


@dataclass(frozen=True, slots=True)
class CatalogRow:
    provider_symbol: str
    name: str
    trading_symbol: str
    instrument_type: str  # INDEX | FUTURE | OPTION
    segment: str  # INDEX | FUT | OPT
    exchange: str
    underlying_symbol: str | None
    expiry_date: str | None  # ISO date
    expiry_kind: str | None  # WEEKLY | MONTHLY
    strike_price: float | None
    option_type: str | None  # CE | PE


_cache: dict[str, tuple[float, list[dict]]] = {}


def _load_dir(dirpath: Path) -> list[dict]:
    rows: list[dict] = []
    if not dirpath.is_dir():
        return rows
    for p in sorted(dirpath.glob("*.json*")):
        mt = p.stat().st_mtime
        hit = _cache.get(str(p))
        if hit and hit[0] == mt:
            rows.extend(hit[1])
            continue
        opener = gzip.open if p.suffix == ".gz" else open
        try:
            with opener(p, "rb") as fh:  # type: ignore[operator]
                data = json.loads(fh.read())
        except (OSError, json.JSONDecodeError):
            continue
        data = data if isinstance(data, list) else []
        _cache[str(p)] = (mt, data)
        rows.extend(data)
    return rows


def _to_row(r: dict) -> CatalogRow | None:
    raw = str(r.get("instrument_type") or "")
    it = _TYPE.get(raw)
    key = r.get("instrument_key")
    if it is None or not key:
        return None
    exp_date = exp_kind = None
    if r.get("expiry"):
        try:
            exp_date = datetime.fromtimestamp(int(r["expiry"]) / 1000, tz=UTC).date().isoformat()
            w = r.get("weekly")
            exp_kind = "WEEKLY" if w is True else "MONTHLY" if w is False else None
        except (TypeError, ValueError, OSError):
            pass
    sp = r.get("strike_price")
    return CatalogRow(
        provider_symbol=str(key),
        name=str(r.get("name") or r.get("trading_symbol") or ""),
        trading_symbol=str(r.get("trading_symbol") or ""),
        instrument_type=it.value,
        segment=_SEG[it],
        exchange=str(r.get("exchange") or ""),
        underlying_symbol=(r.get("underlying_symbol") or r.get("asset_symbol") or None),
        expiry_date=exp_date,
        expiry_kind=exp_kind,
        strike_price=(float(sp) if sp not in (None, "", 0) else None),
        option_type=(
            OptionType.CE.value if raw == "CE" else OptionType.PE.value if raw == "PE" else None
        ),
    )


def search_master(
    dirpath: str | Path,
    q: str,
    *,
    instrument_type: str | None = None,
    exchange: str | None = None,
    limit: int = 50,
) -> list[CatalogRow]:
    q = (q or "").strip().lower()
    if len(q) < 2:
        return []
    out: list[CatalogRow] = []
    for r in _load_dir(Path(dirpath)):
        blob = (
            f"{r.get('instrument_key', '')} {r.get('name', '')} " f"{r.get('trading_symbol', '')}"
        ).lower()
        if q not in blob:
            continue
        cr = _to_row(r)
        if cr is None:
            continue
        if instrument_type and cr.instrument_type != instrument_type:
            continue
        if exchange and cr.exchange.upper() != exchange.upper():
            continue
        out.append(cr)
        if len(out) >= limit * 4:
            break

    def _rank(c: CatalogRow) -> tuple:
        tail = c.provider_symbol.lower().rsplit("|", 1)[-1]
        exact = 0 if (tail == q or c.trading_symbol.lower() == q) else 1
        tprio = {"INDEX": 0, "FUTURE": 1, "OPTION": 2}[c.instrument_type]
        return (exact, tprio, len(c.provider_symbol))

    out.sort(key=_rank)
    return out[:limit]
