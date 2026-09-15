"""Refresh the Upstox instrument master and roll the tracked universe.

Shared by the ``analytical-instruments build-universe`` CLI and the worker's
daily roll job (docs/02 §3.7 / docs/04 §2.3). ``download_upstox_masters`` pulls
the public gzipped masters; ``roll_universe`` re-plans ``option_selection.*``
against the current spot per underlying and rolls ``is_tracked`` to match —
idempotent, so a daily re-run keeps the option strikes centred on the money and
picks up new weekly expiries.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import models as m
from app.db.repositories.instrument_registry import SaInstrumentRegistryRepository
from app.instruments.registry import sync_instruments
from app.instruments.universe import UniverseConfig, plan_universe
from app.providers.upstox.instrument_master import records_from_master
from app.settings_store import load_app_settings

_LOG = structlog.get_logger("instruments.roll")

#: public Upstox instrument-master files (gzipped JSON, no auth)
_MASTER_URL = "https://assets.upstox.com/market-quote/instruments/exchange/{exchange}.json.gz"


def download_upstox_masters(
    dest_dir: str | Path,
    *,
    exchanges: tuple[str, ...] = ("NSE", "BSE"),
    timeout: float = 60.0,
) -> list[Path]:
    """Download the current ``{exchange}.json.gz`` masters into ``dest_dir``.
    Returns the local paths written. Raises ``httpx.HTTPError`` on a bad fetch."""
    out: list[Path] = []
    d = Path(dest_dir)
    d.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for ex in exchanges:
            url = _MASTER_URL.format(exchange=ex)
            resp = client.get(url)
            resp.raise_for_status()
            path = d / f"{ex}.json.gz"
            path.write_bytes(resp.content)
            _LOG.info("master downloaded", exchange=ex, bytes=len(resp.content), path=str(path))
            out.append(path)
    return out


def _spot_by_symbol(
    db: Session, symbols: list[str], overrides: dict[str, float]
) -> dict[str, float]:
    out = dict(overrides)
    for sym in symbols:
        if sym in out:
            continue
        row = db.execute(
            select(m.OhlcvBar.close)
            .join(m.Instrument, m.Instrument.id == m.OhlcvBar.instrument_id)
            .where(m.Instrument.symbol == sym, m.Instrument.instrument_type == "INDEX")
            .order_by(m.OhlcvBar.ts.desc())
            .limit(1)
        ).scalar_one_or_none()
        if row is not None:
            out[sym] = float(row)
    return out


def roll_universe(
    db: Session,
    *,
    master_paths: list[str | Path],
    provider: str,
    spot_overrides: dict[str, float] | None = None,
    today=None,
) -> dict:
    """Plan ``option_selection.*`` against the current spot and roll ``is_tracked``
    to exactly that set. Idempotent. Returns a summary dict."""
    records: list = []
    rej: list = []
    for p in master_paths:
        r, rj = records_from_master(str(p))
        records.extend(r)
        rej.extend(rj)

    cfg = UniverseConfig.from_app_settings(load_app_settings(db))
    spots = _spot_by_symbol(db, list(cfg.underlyings), spot_overrides or {})
    plan = plan_universe(
        records,
        cfg,
        spot_by_symbol=spots,
        today=today or datetime.now(tz=UTC).date(),
    )
    sync = sync_instruments(
        list(plan.records_to_sync),
        provider=provider,
        repo=SaInstrumentRegistryRepository(db),
        extra_rejections=rej,
    )
    keys = set(plan.tracked_keys)
    added = removed = 0
    for iid, ck in db.execute(select(m.Instrument.id, m.Instrument.contract_key)).all():
        want = ck in keys
        cur = db.get(m.Instrument, iid)
        if bool(cur.is_tracked) != want:
            cur.is_tracked = want
            added += int(want)
            removed += int(not want)
    n_tracked = db.execute(
        select(func.count()).select_from(m.Instrument).where(m.Instrument.is_tracked)
    ).scalar_one()

    return {
        "underlyings": list(cfg.underlyings),
        "spots": spots,
        "selected": len(plan.tracked_keys),
        "synced_created": sync.created,
        "synced_updated": sync.updated,
        "tracked_added": added,
        "tracked_removed": removed,
        "now_tracked": n_tracked,
        "per_underlying": plan.per_underlying,
        "quarantined": len(sync.quarantined),
    }
