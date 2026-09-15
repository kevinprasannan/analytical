"""Thin read services for the API (docs/07 §1: validate -> service -> serialise).

Read-only queries against the models. Hot reads (`/analyses`, `/scores`) hit the
``current_*`` projections; history/series/runs hit ``analysis_results``
(docs/07 §1, resolves H8).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from analytical_core.enums import (
    AnalysisScope,
    DataKind,
    InstrumentSegment,
    InstrumentType,
    Timeframe,
)
from app.analysis.applicability import plan_analyses
from app.api.schemas.analysis import VALUE_MODELS, AnalysisItem
from app.api.schemas.common import Provenance
from app.api.schemas.instruments import (
    InstrumentCoverage,
    TimeframeCoverage,
)
from app.db import models as m
from app.db.repositories.protocols import InstrumentView
from app.providers.upstox.capabilities import UPSTOX_CAPABILITIES

_ALL_TF = (Timeframe.M5, Timeframe.M15, Timeframe.H1, Timeframe.D1)


# ======================================================================================
# instruments
# ======================================================================================


def list_instruments(
    db: Session,
    *,
    instrument_type: InstrumentType | None = None,
    segment: str | None = None,
    underlying_id: int | None = None,
    is_tracked: bool | None = None,
    option_type: str | None = None,
    q: str | None = None,
    sort: str = "symbol",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[m.Instrument], int]:
    stmt: Select = select(m.Instrument)
    if instrument_type is not None:
        stmt = stmt.where(m.Instrument.instrument_type == instrument_type)
    if segment is not None:
        stmt = stmt.where(m.Instrument.segment == segment)
    if underlying_id is not None:
        stmt = stmt.where(m.Instrument.underlying_id == underlying_id)
    if is_tracked is not None:
        stmt = stmt.where(m.Instrument.is_tracked.is_(is_tracked))
    if option_type is not None:
        stmt = stmt.where(m.Instrument.option_type == option_type)
    if q:
        like = f"%{q.upper()}%"
        stmt = stmt.where(
            func.upper(m.Instrument.contract_key).like(like)
            | func.upper(m.Instrument.symbol).like(like)
        )

    total = int(db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one())
    col_map = {
        "symbol": m.Instrument.symbol,
        "expiry_date": m.Instrument.expiry_date,
        "strike_price": m.Instrument.strike_price,
        "contract_key": m.Instrument.contract_key,
    }
    field = sort.lstrip("-")
    col = col_map.get(field, m.Instrument.symbol)
    stmt = stmt.order_by(col.desc() if sort.startswith("-") else col.asc(), m.Instrument.id.asc())
    rows = list(db.execute(stmt.limit(limit).offset(offset)).scalars())
    return rows, total


def get_instrument(db: Session, instrument_id: int) -> m.Instrument | None:
    return db.get(m.Instrument, instrument_id)


# --- add / delete (docs/07 §4.2, docs/08 §4.5) --------------------------

_CHILD_PRIORITY = {  # lower = delete first (projections + score_factors before base rows)
    "current_signal_scores": 0,
    "current_analysis_results": 0,
    "signal_scores": 1,
    "analysis_results": 1,
}


def delete_instrument(db: Session, instrument_id: int, *, force: bool = False) -> dict | None:
    """Remove an instrument and every row that references it. Returns per-table
    counts, or ``None`` if the id is unknown. Raises ``ApiError(409)`` if other
    instruments use it as their ``underlying_id`` and ``force`` is not set."""
    from sqlalchemy import text as _text

    from app.api.errors import conflict

    inst = db.get(m.Instrument, instrument_id)
    if inst is None:
        return None
    contract_key = inst.contract_key  # capture before the row is gone
    db.expunge(inst)  # don't let commit try to refresh a deleted row

    dependents = list(
        db.execute(
            select(m.Instrument.id, m.Instrument.contract_key).where(
                m.Instrument.underlying_id == instrument_id
            )
        )
    )
    if dependents and not force:
        raise conflict(
            f"{len(dependents)} instrument(s) reference this as their underlying "
            f"(e.g. {dependents[0][1]}). Delete those first, or pass force=true."
        )

    counts: dict[str, int] = {}

    def _bump(table: str, n: int) -> None:
        if n:
            counts[table] = counts.get(table, 0) + n

    if force:
        for did, _ck in dependents:
            sub = delete_instrument(db, did, force=True)
            if sub:
                for t, n in sub["children"].items():
                    _bump(t, n)
                _bump("instruments", 1)

    # score_factors links via signal_scores, not instrument_id directly
    _bump(
        "score_factors",
        db.execute(
            _text(
                "DELETE FROM score_factors WHERE signal_score_id IN "
                "(SELECT id FROM signal_scores WHERE instrument_id = :i)"
            ),
            {"i": instrument_id},
        ).rowcount,
    )
    child_tables = [
        t
        for (t,) in db.execute(
            _text(
                "SELECT DISTINCT table_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND column_name = 'instrument_id' "
                "AND table_name <> 'instruments'"
            )
        )
    ]
    for t in sorted(child_tables, key=lambda x: _CHILD_PRIORITY.get(x, 5)):
        _bump(
            t,
            db.execute(
                _text(f"DELETE FROM {t} WHERE instrument_id = :i"), {"i": instrument_id}
            ).rowcount,
        )

    db.execute(_text("DELETE FROM instruments WHERE id = :i"), {"i": instrument_id})
    db.commit()
    return {"instrument_id": instrument_id, "contract_key": contract_key, "children": counts}


def create_instrument(db: Session, payload: dict) -> dict:
    """Create one instrument + its active provider mapping (for the current
    ``active_provider``). ``contract_key`` is derived canonically. The worker
    backfills it on the next cycle. Raises ``ApiError`` on a clash / bad ref."""
    from decimal import Decimal as _D

    from app.api.errors import conflict, not_found
    from app.config import get_settings
    from app.instruments.contract_key import build_contract_key

    it = InstrumentType(payload["instrument_type"])
    seg = InstrumentSegment(payload["segment"])
    provider = get_settings().active_provider
    provider_symbol = payload["provider_symbol"].strip()

    expiry = _parse_date(payload.get("expiry_date"))
    from analytical_core.enums import ExpiryKind, OptionType

    exp_kind = ExpiryKind(payload["expiry_kind"]) if payload.get("expiry_kind") else None
    strike = _D(str(payload["strike_price"])) if payload.get("strike_price") is not None else None
    opt = OptionType(payload["option_type"]) if payload.get("option_type") else None

    underlying_id = None
    underlying_symbol = payload.get("underlying_symbol")
    if payload.get("underlying_contract_key"):
        u = db.execute(
            select(m.Instrument.id, m.Instrument.symbol).where(
                m.Instrument.contract_key == payload["underlying_contract_key"]
            )
        ).one_or_none()
        if u is None:
            raise not_found(f"underlying {payload['underlying_contract_key']}")
        underlying_id = u[0]
        underlying_symbol = underlying_symbol or payload["underlying_contract_key"].split("-")[0]
    underlying_symbol = underlying_symbol or payload.get("symbol") or ""

    ck = build_contract_key(
        instrument_type=it,
        underlying_symbol=underlying_symbol,
        expiry_date=expiry,
        expiry_kind=exp_kind,
        strike_price=strike,
        option_type=opt,
    )
    if db.execute(select(m.Instrument.id).where(m.Instrument.contract_key == ck)).first():
        raise conflict(f"instrument {ck} already exists")
    if db.execute(
        select(m.ProviderInstrumentMap.id).where(
            m.ProviderInstrumentMap.provider == provider,
            m.ProviderInstrumentMap.provider_symbol == provider_symbol,
        )
    ).first():
        raise conflict(f"provider_symbol {provider_symbol!r} is already mapped ({provider})")

    inst = m.Instrument(
        contract_key=ck,
        symbol=payload.get("symbol") or underlying_symbol,
        display_name=payload.get("display_name"),
        exchange=payload.get("exchange", "NSE"),
        segment=seg,
        instrument_type=it,
        underlying_id=underlying_id,
        expiry_date=expiry,
        expiry_kind=exp_kind,
        strike_price=strike,
        option_type=opt,
        is_active=True,
        is_tracked=bool(payload.get("is_tracked", True)),
        has_volume=it is not InstrumentType.INDEX,
        has_intraday_oi=it in (InstrumentType.FUTURE, InstrumentType.OPTION),
    )
    db.add(inst)
    db.flush()
    db.add(
        m.ProviderInstrumentMap(
            instrument_id=inst.id,
            provider=provider,
            provider_symbol=provider_symbol,
            is_active=True,
        )
    )
    db.commit()
    return {"instrument_id": inst.id, "contract_key": ck, "provider": provider}


def _parse_date(v):
    from datetime import date as _date

    if not v:
        return None
    return v if isinstance(v, _date) else _date.fromisoformat(str(v))


def provider_map_for(db: Session, instrument_id: int) -> list[m.ProviderInstrumentMap]:
    return list(
        db.execute(
            select(m.ProviderInstrumentMap).where(
                m.ProviderInstrumentMap.instrument_id == instrument_id
            )
        ).scalars()
    )


def applicable_analyses(inst: m.Instrument) -> list[str]:
    view = InstrumentView(
        id=inst.id,
        contract_key=inst.contract_key,
        instrument_type=inst.instrument_type,
        has_volume=inst.has_volume,
        has_intraday_oi=inst.has_intraday_oi,
        provider_symbol="",
    )
    now = datetime.now(tz=_utc())
    plans = plan_analyses(view, UPSTOX_CAPABILITIES, as_of=now, session_date=now.date())
    seen: list[str] = []
    for p in plans:
        if p.status.value in ("OK",) and p.analysis_key not in seen:
            seen.append(p.analysis_key)
    return seen


def coverage(db: Session, instrument_id: int, provider: str) -> InstrumentCoverage:
    tfs: list[TimeframeCoverage] = []
    for tf in (Timeframe.M1, *_ALL_TF):
        agg = db.execute(
            select(
                func.min(m.OhlcvBar.ts),
                func.max(m.OhlcvBar.ts),
                func.count(),
            ).where(
                m.OhlcvBar.instrument_id == instrument_id,
                m.OhlcvBar.timeframe == tf,
                m.OhlcvBar.provider == provider,
            )
        ).one()
        earliest, latest, count = agg
        latest_final: bool | None = None
        if latest is not None:
            latest_final = db.execute(
                select(m.OhlcvBar.is_final).where(
                    m.OhlcvBar.instrument_id == instrument_id,
                    m.OhlcvBar.timeframe == tf,
                    m.OhlcvBar.provider == provider,
                    m.OhlcvBar.ts == latest,
                )
            ).scalar_one()
        wm = db.execute(
            select(
                m.IngestionWatermark.last_status,
                m.IngestionWatermark.last_complete_ts,
                m.IngestionWatermark.last_verified_ts,
            ).where(
                m.IngestionWatermark.instrument_id == instrument_id,
                m.IngestionWatermark.timeframe == tf,
                m.IngestionWatermark.data_kind == DataKind.OHLCV,
                m.IngestionWatermark.provider == provider,
            )
        ).one_or_none()
        tfs.append(
            TimeframeCoverage(
                timeframe=tf,
                earliest_bar_ts=earliest,
                latest_bar_ts=latest,
                latest_is_final=latest_final,
                bar_count=int(count),
                watermark_status=wm[0] if wm else None,
                watermark_last_complete_ts=wm[1] if wm else None,
                watermark_last_verified_ts=wm[2] if wm else None,
            )
        )
    last_oi = db.execute(
        select(m.OpenInterest.ts, m.OpenInterest.oi)
        .where(m.OpenInterest.instrument_id == instrument_id, m.OpenInterest.provider == provider)
        .order_by(m.OpenInterest.ts.desc())
        .limit(1)
    ).one_or_none()
    return InstrumentCoverage(
        instrument_id=instrument_id,
        timeframes=tfs,
        last_oi_ts=last_oi[0] if last_oi else None,
        last_oi=int(last_oi[1]) if last_oi else None,
    )


# ======================================================================================
# market data
# ======================================================================================


def list_bars(
    db: Session,
    instrument_id: int,
    *,
    timeframe: Timeframe,
    provider: str,
    start: datetime | None,
    end: datetime | None,
    limit: int,
    offset: int,
    include_forming: bool,
) -> tuple[list[m.OhlcvBar], int]:
    stmt = select(m.OhlcvBar).where(
        m.OhlcvBar.instrument_id == instrument_id,
        m.OhlcvBar.timeframe == timeframe,
        m.OhlcvBar.provider == provider,
    )
    if start is not None:
        stmt = stmt.where(m.OhlcvBar.ts >= start)
    if end is not None:
        stmt = stmt.where(m.OhlcvBar.ts < end)
    if not include_forming:
        stmt = stmt.where(m.OhlcvBar.is_final.is_(True))
    total = int(db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one())
    rows = list(
        db.execute(stmt.order_by(m.OhlcvBar.ts.desc()).limit(limit).offset(offset)).scalars()
    )
    rows.reverse()
    return rows, total


def list_oi(
    db: Session,
    instrument_id: int,
    *,
    timeframe: Timeframe,
    provider: str,
    start: datetime | None,
    end: datetime | None,
    limit: int,
    offset: int,
) -> tuple[list[m.OpenInterest], int]:
    stmt = select(m.OpenInterest).where(
        m.OpenInterest.instrument_id == instrument_id,
        m.OpenInterest.timeframe == timeframe,
        m.OpenInterest.provider == provider,
    )
    if start is not None:
        stmt = stmt.where(m.OpenInterest.ts >= start)
    if end is not None:
        stmt = stmt.where(m.OpenInterest.ts < end)
    total = int(db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one())
    rows = list(
        db.execute(stmt.order_by(m.OpenInterest.ts.desc()).limit(limit).offset(offset)).scalars()
    )
    rows.reverse()
    return rows, total


# ======================================================================================
# analyses (current projection + history)
# ======================================================================================


def _item_from_current(row: m.CurrentAnalysisResult) -> AnalysisItem:
    summary = row.summary or {}
    values = summary.get("values", {})
    return AnalysisItem(
        instrument_id=row.instrument_id,
        analysis_key=row.analysis_key,
        scope=row.scope,
        timeframe=row.timeframe,
        session_date=row.session_date,
        snapshot_ts=row.snapshot_ts,
        status=row.status,
        as_of_ts=row.as_of_ts,
        reason=values.get("reason"),
        carried=bool(row.carried),
        values={} if "reason" in values else values,
        aux=summary.get("aux", {}),
        provenance=Provenance(
            algo_version=row.algo_version,
            params_id="",
            params_hash=row.params_hash,
        ),
    )


def list_current_analyses(
    db: Session,
    *,
    timeframe: Timeframe | None,
    instrument_type: InstrumentType | None,
    analysis_key: str | None,
    status: str | None,
    is_tracked: bool | None,
    limit: int,
    offset: int,
) -> tuple[list[AnalysisItem], int]:
    stmt = select(m.CurrentAnalysisResult).join(
        m.Instrument, m.Instrument.id == m.CurrentAnalysisResult.instrument_id
    )
    if timeframe is not None:
        stmt = stmt.where(m.CurrentAnalysisResult.timeframe == timeframe)
    if instrument_type is not None:
        stmt = stmt.where(m.Instrument.instrument_type == instrument_type)
    if analysis_key is not None:
        stmt = stmt.where(m.CurrentAnalysisResult.analysis_key == analysis_key)
    if status is not None:
        stmt = stmt.where(m.CurrentAnalysisResult.status == status)
    if is_tracked is not None:
        stmt = stmt.where(m.Instrument.is_tracked.is_(is_tracked))
    total = int(db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one())
    rows = db.execute(
        stmt.order_by(
            m.CurrentAnalysisResult.instrument_id,
            m.CurrentAnalysisResult.analysis_key,
            m.CurrentAnalysisResult.scope_ref,
        )
        .limit(limit)
        .offset(offset)
    ).scalars()
    return [_item_from_current(r) for r in rows], total


def instrument_analyses(
    db: Session, instrument_id: int, timeframe: Timeframe
) -> list[AnalysisItem]:
    rows = db.execute(
        select(m.CurrentAnalysisResult).where(
            m.CurrentAnalysisResult.instrument_id == instrument_id,
            (
                (m.CurrentAnalysisResult.scope == AnalysisScope.PER_TIMEFRAME)
                & (m.CurrentAnalysisResult.timeframe == timeframe)
            )
            | (m.CurrentAnalysisResult.scope != AnalysisScope.PER_TIMEFRAME),
        )
    ).scalars()
    return [_item_from_current(r) for r in rows]


def one_analysis(
    db: Session, instrument_id: int, analysis_key: str, timeframe: Timeframe | None = None
) -> AnalysisItem | None:
    """One current analysis item. ``timeframe`` selects the ``PER_TIMEFRAME``
    variant; omit it for a ``SESSION`` / ``SNAPSHOT`` analysis (market_profile,
    or an index's not-applicable open_interest). A per-timeframe analysis needs a
    ``timeframe``."""
    stmt = select(m.CurrentAnalysisResult).where(
        m.CurrentAnalysisResult.instrument_id == instrument_id,
        m.CurrentAnalysisResult.analysis_key == analysis_key,
    )
    if timeframe is not None:
        stmt = stmt.where(
            (
                (m.CurrentAnalysisResult.scope == AnalysisScope.PER_TIMEFRAME)
                & (m.CurrentAnalysisResult.timeframe == timeframe)
            )
            | (m.CurrentAnalysisResult.scope != AnalysisScope.PER_TIMEFRAME)
        )
    else:
        stmt = stmt.where(m.CurrentAnalysisResult.scope != AnalysisScope.PER_TIMEFRAME)
    row = db.execute(stmt.limit(1)).scalars().first()
    if row is None:
        return None
    item = _item_from_current(row)
    full = db.get(m.AnalysisResultRow, row.analysis_result_id)
    # recompute-guard rows only carry {carried, carried_from_result_id}; walk the
    # chain to the real result that holds values/meta.
    for _ in range(16):
        if full is None or not full.result.get("carried"):
            break
        nxt = full.result.get("carried_from_result_id")
        if not nxt:
            break
        full = db.get(m.AnalysisResultRow, nxt)
    if full is not None and full.result:
        res = full.result
        meta = res.get("meta", {})
        values = res.get("values", {})
        item.values = {} if "reason" in values else values
        item.aux = res.get("aux", {})
        item.warnings = list(res.get("warnings", []))
        prov = {k: meta[k] for k in Provenance.model_fields if meta.get(k) is not None}
        if {"algo_version", "params_id", "params_hash"} <= prov.keys():
            item.provenance = Provenance(**prov)
        model = VALUE_MODELS.get(analysis_key)
        if model is not None and item.values and item.status.value == "OK":
            item.typed_values = model(**item.values)
    return item


def analysis_series(
    db: Session,
    instrument_id: int,
    analysis_key: str,
    *,
    timeframe: Timeframe,
    start: datetime | None,
    end: datetime | None,
    limit: int,
) -> list[dict[str, Any]]:
    stmt = select(m.AnalysisResultRow).where(
        m.AnalysisResultRow.instrument_id == instrument_id,
        m.AnalysisResultRow.analysis_key == analysis_key,
        m.AnalysisResultRow.timeframe == timeframe,
        m.AnalysisResultRow.carried.is_(False),
        m.AnalysisResultRow.input_window_end.is_not(None),
    )
    if start is not None:
        stmt = stmt.where(m.AnalysisResultRow.input_window_end >= start)
    if end is not None:
        stmt = stmt.where(m.AnalysisResultRow.input_window_end < end)
    rows = db.execute(
        stmt.order_by(m.AnalysisResultRow.input_window_end.desc()).limit(limit)
    ).scalars()
    out = [
        {
            "ts": r.input_window_end,
            "status": r.status.value,
            "values": (r.result or {}).get("values", {}),
        }
        for r in rows
    ]
    out.reverse()
    return out


def analysis_runs(
    db: Session,
    instrument_id: int,
    analysis_key: str,
    *,
    scope: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    stmt = select(m.AnalysisResultRow).where(
        m.AnalysisResultRow.instrument_id == instrument_id,
        m.AnalysisResultRow.analysis_key == analysis_key,
    )
    if scope is not None:
        stmt = stmt.where(m.AnalysisResultRow.scope == scope)
    rows = db.execute(stmt.order_by(m.AnalysisResultRow.run_id.desc()).limit(limit)).scalars()
    return [
        {
            "run_id": r.run_id,
            "scope_key": r.scope_key,
            "status": r.status.value,
            "carried": bool(r.carried),
            "carried_from_result_id": r.carried_from_result_id,
            "as_of_ts": r.as_of_ts,
            "algo_version": r.algo_version,
            "params_hash": r.params_hash,
            "input_window_end": r.input_window_end,
            "bars_used": r.bars_used,
            "coverage_ratio": float(r.coverage_ratio) if r.coverage_ratio is not None else None,
        }
        for r in rows
    ]


# ======================================================================================
# runs
# ======================================================================================


def list_runs(db: Session, *, limit: int, offset: int) -> tuple[list[m.AnalysisRun], int]:
    total = int(db.execute(select(func.count()).select_from(m.AnalysisRun)).scalar_one())
    rows = list(
        db.execute(
            select(m.AnalysisRun)
            .order_by(m.AnalysisRun.cycle_seq.desc())
            .limit(limit)
            .offset(offset)
        ).scalars()
    )
    return rows, total


def get_run(db: Session, run_id: int) -> m.AnalysisRun | None:
    return db.get(m.AnalysisRun, run_id)


def find_run_by_idempotency_key(db: Session, key: str, window_seconds: int) -> m.AnalysisRun | None:
    """Most recent run whose ``config_snapshot.idempotency_key`` matches ``key``,
    started within ``window_seconds`` (docs/07 §3)."""
    cutoff = datetime.now(tz=UTC) - timedelta(seconds=window_seconds)
    return db.execute(
        select(m.AnalysisRun)
        .where(
            m.AnalysisRun.config_snapshot["idempotency_key"].astext == key,
            m.AnalysisRun.started_at >= cutoff,
        )
        .order_by(m.AnalysisRun.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def stale_result_counts(db: Session) -> dict[str, int]:
    """How many hot-projection rows were produced by an engine version behind the
    current code (docs/07 §4.1). ``params_hash`` drift from a config change is not
    counted here — only ``algo_version`` / ``scoring_version``. Degrades to zeros
    if the DB is unreachable (``/health/ready`` is the DB-health endpoint)."""
    from analytical_core.versioning import ALGO_VERSION, SCORING_VERSION

    try:
        analysis = int(
            db.execute(
                select(func.count())
                .select_from(m.CurrentAnalysisResult)
                .where(m.CurrentAnalysisResult.algo_version != ALGO_VERSION)
            ).scalar_one()
        )
        scoring = int(
            db.execute(
                select(func.count())
                .select_from(m.CurrentSignalScore)
                .join(m.SignalScore, m.SignalScore.id == m.CurrentSignalScore.signal_score_id)
                .where(m.SignalScore.scoring_version != SCORING_VERSION)
            ).scalar_one()
        )
    except SQLAlchemyError:
        db.rollback()
        return {"analysis_results": 0, "signal_scores": 0}
    return {"analysis_results": analysis, "signal_scores": scoring}


def run_phase_status(db: Session, run_id: int) -> list[m.RunPhaseStatus]:
    return list(
        db.execute(select(m.RunPhaseStatus).where(m.RunPhaseStatus.run_id == run_id)).scalars()
    )


def run_instrument_status(db: Session, run_id: int) -> list[m.RunInstrumentStatus]:
    return list(
        db.execute(
            select(m.RunInstrumentStatus).where(m.RunInstrumentStatus.run_id == run_id)
        ).scalars()
    )


# ======================================================================================
# scores (docs/07 §4.5) — hot list from current_signal_scores
# ======================================================================================


def list_current_scores(
    db: Session,
    *,
    timeframe: Timeframe,
    instrument_type: InstrumentType | None,
    label: str | None,
    min_confidence: float | None,
    sort: str,
    limit: int,
    offset: int,
):
    stmt = (
        select(m.CurrentSignalScore, m.Instrument.contract_key, m.Instrument.symbol)
        .join(m.Instrument, m.Instrument.id == m.CurrentSignalScore.instrument_id)
        .where(m.CurrentSignalScore.timeframe == timeframe)
    )
    if instrument_type is not None:
        stmt = stmt.where(m.Instrument.instrument_type == instrument_type)
    if label is not None:
        stmt = stmt.where(m.CurrentSignalScore.effective_label == label)
    if min_confidence is not None:
        stmt = stmt.where(m.CurrentSignalScore.confidence >= min_confidence)

    total = int(db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one())
    col = {
        "composite_score": m.CurrentSignalScore.composite_score,
        "confidence": m.CurrentSignalScore.confidence,
        "as_of_ts": m.CurrentSignalScore.as_of_ts,
    }.get(sort.lstrip("-"), m.CurrentSignalScore.composite_score)
    stmt = stmt.order_by(col.desc() if sort.startswith("-") else col.asc())
    rows = db.execute(stmt.limit(limit).offset(offset)).all()
    return rows, total


def score_detail(db: Session, instrument_id: int, timeframe: Timeframe):
    cur = db.execute(
        select(m.CurrentSignalScore).where(
            m.CurrentSignalScore.instrument_id == instrument_id,
            m.CurrentSignalScore.timeframe == timeframe,
        )
    ).scalar_one_or_none()
    if cur is None:
        return None
    row = db.get(m.SignalScore, cur.signal_score_id)
    factors = db.execute(
        select(m.ScoreFactor).where(m.ScoreFactor.signal_score_id == cur.signal_score_id)
    ).scalars()
    return cur, row, list(factors)


def market_profile_view(db: Session, instrument_id: int, session_date, profile_type: str | None):
    q = select(m.MarketProfileSession).where(
        m.MarketProfileSession.instrument_id == instrument_id,
        m.MarketProfileSession.session_date == session_date,
    )
    if profile_type is not None:
        q = q.where(m.MarketProfileSession.profile_type == profile_type)
    rows = list(db.execute(q).scalars())
    if not rows:
        return None
    # close_* live on the analysis_results market_profile row for the session
    ar = db.execute(
        select(m.AnalysisResultRow.result)
        .where(
            m.AnalysisResultRow.instrument_id == instrument_id,
            m.AnalysisResultRow.analysis_key == "market_profile",
            m.AnalysisResultRow.session_date == session_date,
        )
        .order_by(m.AnalysisResultRow.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    close_vals = (ar or {}).get("values", {}) if ar else {}
    return rows, close_vals


def latest_market_profile_date(db: Session, instrument_id: int):
    return db.execute(
        select(func.max(m.MarketProfileSession.session_date)).where(
            m.MarketProfileSession.instrument_id == instrument_id
        )
    ).scalar()


def score_history(db: Session, instrument_id: int, timeframe: Timeframe, *, limit: int):
    rows = db.execute(
        select(m.SignalScore)
        .where(
            m.SignalScore.instrument_id == instrument_id,
            m.SignalScore.timeframe == timeframe,
        )
        .order_by(m.SignalScore.run_id.desc())
        .limit(limit)
    ).scalars()
    out = list(rows)
    out.reverse()
    return out


def _utc():
    from datetime import UTC

    return UTC


# ======================================================================================
# option chain (docs/05 §11, docs/07 §4.4)
# ======================================================================================


def option_expiries(db: Session, underlying_id: int) -> list:
    return list(
        db.execute(
            select(m.Instrument.expiry_date)
            .where(
                m.Instrument.instrument_type == InstrumentType.OPTION,
                m.Instrument.underlying_id == underlying_id,
                m.Instrument.expiry_date.is_not(None),
            )
            .distinct()
            .order_by(m.Instrument.expiry_date)
        ).scalars()
    )


def option_chain(db: Session, underlying_id: int, *, expiry=None, provider: str | None = None):
    """Assemble the option chain for ``underlying_id`` at ``expiry`` (default: the
    nearest). Returns ``None`` if the underlying has no option instruments; raises
    nothing else. Pure assembly is in ``analytical_core.options``."""
    from datetime import datetime

    from analytical_core.options import LegInput, build_chain
    from app.config import get_settings

    under = db.get(m.Instrument, underlying_id)
    if under is None:
        return None
    provider = provider or get_settings().active_provider

    expiries = option_expiries(db, underlying_id)
    if not expiries:
        return None
    if expiry is None:
        today = datetime.now(tz=_utc()).date()
        expiry = next((e for e in expiries if e >= today), expiries[-1])
    elif expiry not in expiries:
        return None

    opts = list(
        db.execute(
            select(m.Instrument).where(
                m.Instrument.instrument_type == InstrumentType.OPTION,
                m.Instrument.underlying_id == underlying_id,
                m.Instrument.expiry_date == expiry,
            )
        ).scalars()
    )

    def _last_bar(iid: int):
        # options are ingested M1-only (chain-only); indices/futures have M5
        for tf in (Timeframe.M5, Timeframe.M1):
            row = db.execute(
                select(m.OhlcvBar.close, m.OhlcvBar.volume)
                .where(
                    m.OhlcvBar.instrument_id == iid,
                    m.OhlcvBar.timeframe == tf,
                    m.OhlcvBar.provider == provider,
                )
                .order_by(m.OhlcvBar.ts.desc())
                .limit(1)
            ).one_or_none()
            if row is not None:
                return row
        return None

    spot_row = _last_bar(underlying_id)
    if spot_row is None or spot_row[0] is None:
        return None
    spot = float(spot_row[0])

    opt_ids = [o.id for o in opts]

    # this session's O/H/L/C + volume per option, aggregated from its M1 bars
    from app.ingestion.session import IST, nse_session_window, trading_date_of

    _now = datetime.now(tz=_utc())
    _sess_open = nse_session_window(trading_date_of(_now.astimezone(IST))).open_utc
    sess_ohlc: dict[int, dict] = {}
    if opt_ids:
        for iid, o_, h_, l_, c_, v_ in db.execute(
            select(
                m.OhlcvBar.instrument_id,
                m.OhlcvBar.open,
                m.OhlcvBar.high,
                m.OhlcvBar.low,
                m.OhlcvBar.close,
                m.OhlcvBar.volume,
            )
            .where(
                m.OhlcvBar.instrument_id.in_(opt_ids),
                m.OhlcvBar.timeframe == Timeframe.M1,
                m.OhlcvBar.provider == provider,
                m.OhlcvBar.ts >= _sess_open,
            )
            .order_by(m.OhlcvBar.instrument_id, m.OhlcvBar.ts)
        ):
            d = sess_ohlc.get(iid)
            if d is None:
                sess_ohlc[iid] = {
                    "open": float(o_),
                    "high": float(h_),
                    "low": float(l_),
                    "close": float(c_),
                    "vol": int(v_ or 0),
                }
            else:
                d["high"] = max(d["high"], float(h_))
                d["low"] = min(d["low"], float(l_))
                d["close"] = float(c_)
                d["vol"] += int(v_ or 0)

    # oi_change (+ oi if the analysis has enough history) from the open_interest analysis
    oi_analysis = {
        r.instrument_id: (r.summary or {}).get("values", {})
        for r in db.execute(
            select(m.CurrentAnalysisResult).where(
                m.CurrentAnalysisResult.instrument_id.in_(opt_ids),
                m.CurrentAnalysisResult.analysis_key == "open_interest",
            )
        ).scalars()
    }
    # latest raw OI per option — the primary source (works before the analysis has history)
    latest_oi: dict[int, int] = {}
    for iid, oi in db.execute(
        select(m.OpenInterest.instrument_id, m.OpenInterest.oi)
        .where(m.OpenInterest.instrument_id.in_(opt_ids), m.OpenInterest.provider == provider)
        .order_by(m.OpenInterest.instrument_id, m.OpenInterest.ts.desc())
    ):
        latest_oi.setdefault(iid, int(oi))

    legs: list = []
    for o in opts:
        bar = _last_bar(o.id)
        oiv = oi_analysis.get(o.id, {})
        s = sess_ohlc.get(o.id)
        ltp = (
            s["close"] if s is not None else (float(bar[0]) if bar and bar[0] is not None else None)
        )
        vol = s["vol"] if s is not None else (int(bar[1]) if bar and bar[1] is not None else None)
        legs.append(
            LegInput(
                strike=float(o.strike_price),
                option_type=o.option_type.value,
                ltp=ltp,
                oi=latest_oi.get(o.id, oiv.get("oi")),
                oi_change=oiv.get("oi_change"),
                volume=vol,
                day_open=s["open"] if s is not None else None,
                day_high=s["high"] if s is not None else None,
                day_low=s["low"] if s is not None else None,
            )
        )

    stored = read_settings(db)
    rate = float(stored.get("options.risk_free_rate", 0.065))
    dy = float(stored.get("options.dividend_yield", 0.0))
    return build_chain(
        underlying_symbol=under.symbol,
        spot=spot,
        expiry=expiry,
        now=datetime.now(tz=_utc()),
        risk_free_rate=rate,
        legs=legs,
        dividend_yield=dy,
    )


# ======================================================================================
# Premium decay — theta vs. the session's actual move (docs/05 §11.6, docs/07 §4.23)
# ======================================================================================


def premium_decay(db: Session, underlying_id: int, *, expiry=None, provider: str | None = None):
    """Theta-implied decay vs. the session's actual premium move, per strike, for
    ``underlying_id`` at ``expiry`` (default: the nearest). Reuses ``option_chain``
    for the live IV/theta/LTP ladder, adds each leg's premium at today's session
    open, and lets ``analytical_core.options.decay`` compare the two. Returns
    ``None`` when the underlying has no option chain."""
    from datetime import date, datetime

    from analytical_core.options import DecayConfig, DecayLegInput, build_premium_decay
    from app.config import get_settings
    from app.ingestion.session import IST, nse_session_window, trading_date_of

    chain = option_chain(db, underlying_id, expiry=expiry, provider=provider)
    if chain is None:
        return None
    provider = provider or get_settings().active_provider

    now = datetime.now(tz=_utc())
    session_open = nse_session_window(trading_date_of(now.astimezone(IST))).open_utc
    expiry_date = date.fromisoformat(chain.expiry)

    opts = list(
        db.execute(
            select(
                m.Instrument.id,
                m.Instrument.strike_price,
                m.Instrument.option_type,
                m.Instrument.lot_size,
            ).where(
                m.Instrument.instrument_type == InstrumentType.OPTION,
                m.Instrument.underlying_id == underlying_id,
                m.Instrument.expiry_date == expiry_date,
            )
        )
    )
    key_by_id: dict[int, tuple[float, str]] = {}
    lot_size_by: dict[tuple[float, str], int | None] = {}
    for iid, strike, otype, lot in opts:
        side = otype.value if hasattr(otype, "value") else str(otype)
        key = (float(strike), side)
        key_by_id[iid] = key
        lot_size_by[key] = lot
    opt_ids = list(key_by_id)

    # premium at today's session open, per leg — earliest M1 close at/after the open
    price_at_open: dict[tuple[float, str], float] = {}
    if opt_ids:
        seen: set[int] = set()
        for iid, _ts, close in db.execute(
            select(m.OhlcvBar.instrument_id, m.OhlcvBar.ts, m.OhlcvBar.close)
            .where(
                m.OhlcvBar.instrument_id.in_(opt_ids),
                m.OhlcvBar.timeframe == Timeframe.M1,
                m.OhlcvBar.provider == provider,
                m.OhlcvBar.ts >= session_open,
            )
            .order_by(m.OhlcvBar.instrument_id, m.OhlcvBar.ts)
        ):
            if iid in seen:
                continue
            seen.add(iid)
            key = key_by_id.get(iid)
            if key is not None:
                price_at_open[key] = float(close)

    legs_in = [
        DecayLegInput(
            strike=row.strike,
            option_type=leg.option_type,
            ltp=leg.ltp,
            iv=leg.iv,
            theta=leg.theta,
            lot_size=lot_size_by.get((row.strike, leg.option_type)),
            price_at_open=price_at_open.get((row.strike, leg.option_type)),
        )
        for row in chain.rows
        for leg in (row.call, row.put)
        if leg is not None
    ]

    stored = read_settings(db)
    cfg = DecayConfig(
        price_epsilon_abs=float(stored.get("options.decay_epsilon_abs", 0.5)),
        gap_epsilon_frac=float(stored.get("options.decay_gap_epsilon_frac", 0.3)),
    )
    return build_premium_decay(
        underlying_symbol=chain.underlying_symbol,
        spot=chain.spot,
        expiry=chain.expiry,
        days_to_expiry=chain.days_to_expiry,
        atm_strike=chain.atm_strike,
        now=now,
        session_open=session_open,
        legs=legs_in,
        config=cfg,
    )


# ======================================================================================
# Option-strategy suggestions (docs/05 §11.5, docs/07 §4.13)
# ======================================================================================


def option_strategies(
    db: Session,
    underlying_id: int,
    *,
    expiry=None,
    provider: str | None = None,
    wing_points: float | None = None,
    calendars: bool = True,
):
    """OI-based option-structure suggestions for ``underlying_id`` at ``expiry``.

    Reuses :func:`option_chain` for the per-strike OI / ΔOI / LTP + IV, then the
    pure ``analytical_core.options.strategy`` classifier + templates. Each
    suggestion carries a lognormal ``pop`` (on the ATM IV), ``reward_risk`` and
    an ``edge_score`` = pop x reward_risk; the book is ranked best-edge first.
    When ``calendars`` and a later expiry exists it is loaded so calendar
    spreads can be offered on a range read. Returns ``None`` when the underlying
    has no option chain. Illustrative analytical output, not advice
    (owner-authorised revision of decision 15)."""
    from datetime import date, datetime

    from analytical_core.options import StrikeQuote, build_strategy_book
    from analytical_core.options.strategy import StrategyConfig

    chain = option_chain(db, underlying_id, expiry=expiry, provider=provider)
    if chain is None:
        return None

    def _quotes(ch):
        return [
            StrikeQuote(
                strike=row.strike,
                ce_oi=row.call.oi if row.call else None,
                ce_oi_change=row.call.oi_change if row.call else None,
                ce_ltp=row.call.ltp if row.call else None,
                pe_oi=row.put.oi if row.put else None,
                pe_oi_change=row.put.oi_change if row.put else None,
                pe_ltp=row.put.ltp if row.put else None,
            )
            for row in ch.rows
        ]

    # ATM IV: average of the ATM strike's call & put IV (whichever are present)
    atm_iv = None
    atm_row = next((r for r in chain.rows if r.strike == chain.atm_strike), None)
    if atm_row is not None:
        ivs = [
            x.iv
            for x in (atm_row.call, atm_row.put)
            if x is not None and x.iv is not None and x.iv > 0
        ]
        atm_iv = sum(ivs) / len(ivs) if ivs else None

    # a later expiry for calendars
    far_quotes = far_expiry = None
    if calendars:
        exps = option_expiries(db, underlying_id)
        this_exp = date.fromisoformat(chain.expiry)
        nxt = next((e for e in exps if e > this_exp), None)
        if nxt is not None:
            far_chain = option_chain(db, underlying_id, expiry=nxt, provider=provider)
            if far_chain is not None:
                far_quotes, far_expiry = _quotes(far_chain), nxt

    stored = read_settings(db)
    cfg = StrategyConfig(
        wing_steps=int(stored.get("options.strategy_wing_steps", 2)),
        wing_points=(
            wing_points if wing_points is not None else stored.get("options.strategy_wing_points")
        ),
        max_suggestions=int(stored.get("options.strategy_max_suggestions", 8)),
        min_reward_risk=float(stored.get("options.strategy_min_reward_risk", 0.0)),
    )
    return build_strategy_book(
        underlying_symbol=chain.underlying_symbol,
        quotes=_quotes(chain),
        spot=chain.spot,
        expiry=date.fromisoformat(chain.expiry),
        now=datetime.now(tz=_utc()),
        config=cfg,
        atm_iv=atm_iv,
        t_years=chain.t_years,
        risk_free_rate=chain.risk_free_rate,
        far_quotes=far_quotes,
        far_expiry=far_expiry,
    )


# ======================================================================================
# OI pulse (docs/05 §11.4, docs/07 §4.11)
# ======================================================================================


def oi_pulse(
    db: Session,
    underlying_id: int,
    *,
    expiry=None,
    provider: str | None = None,
    trace_up: int | None = None,
    trace_down: int | None = None,
    recent_window_min: int | None = None,
):
    """Intraday trending-OI view for one expiry: strike-ladder OI change + buildup,
    PCR / max-pain now vs. at the open, OI walls, net-writing bias, session trace.
    Computed on read from this session's per-minute ``open_interest`` + option M1
    premium bars. ``None`` if the underlying has no options / no spot / unknown expiry.

    ``recent_window_min`` overrides the ``OiPulseConfig`` default (15) for every
    ``*_recent`` field / the trace step's baseline."""
    from datetime import datetime as _dt

    from analytical_core.options import OiLegSeries, OiPulseConfig, build_oi_pulse
    from app.config import get_settings
    from app.ingestion.session import IST, nse_session_window, trading_date_of

    under = db.get(m.Instrument, underlying_id)
    if under is None:
        return None
    provider = provider or get_settings().active_provider

    expiries = option_expiries(db, underlying_id)
    if not expiries:
        return None
    now = _dt.now(tz=_utc())
    if expiry is None:
        expiry = next((e for e in expiries if e >= now.date()), expiries[-1])
    elif expiry not in expiries:
        return None

    opts = list(
        db.execute(
            select(m.Instrument.id, m.Instrument.strike_price, m.Instrument.option_type).where(
                m.Instrument.instrument_type == InstrumentType.OPTION,
                m.Instrument.underlying_id == underlying_id,
                m.Instrument.expiry_date == expiry,
            )
        )
    )
    if not opts:
        return None
    opt_ids = [o.id for o in opts]

    spot_row = db.execute(
        select(m.OhlcvBar.close)
        .where(
            m.OhlcvBar.instrument_id == underlying_id,
            m.OhlcvBar.timeframe.in_((Timeframe.M1, Timeframe.M5)),
            m.OhlcvBar.provider == provider,
        )
        .order_by(m.OhlcvBar.ts.desc())
        .limit(1)
    ).scalar_one_or_none()
    if spot_row is None:
        return None
    spot = float(spot_row)

    # session window anchored on the current trading date; before the open, look
    # back a few hours so a quiet pre-market still yields the prior session's tail
    window = nse_session_window(trading_date_of(now.astimezone(IST)))
    session_open = min(window.open_utc, now - timedelta(hours=1))

    oi_series: dict[int, list[tuple]] = {i: [] for i in opt_ids}
    for iid, ts, oi in db.execute(
        select(m.OpenInterest.instrument_id, m.OpenInterest.ts, m.OpenInterest.oi)
        .where(
            m.OpenInterest.instrument_id.in_(opt_ids),
            m.OpenInterest.provider == provider,
            m.OpenInterest.ts >= session_open,
        )
        .order_by(m.OpenInterest.instrument_id, m.OpenInterest.ts)
    ):
        oi_series[iid].append((ts.astimezone(UTC), int(oi)))

    px_series: dict[int, list[tuple]] = {i: [] for i in opt_ids}
    vol_series: dict[int, list[tuple]] = {i: [] for i in opt_ids}
    for iid, ts, close, vol in db.execute(
        select(m.OhlcvBar.instrument_id, m.OhlcvBar.ts, m.OhlcvBar.close, m.OhlcvBar.volume)
        .where(
            m.OhlcvBar.instrument_id.in_(opt_ids),
            m.OhlcvBar.timeframe == Timeframe.M1,
            m.OhlcvBar.provider == provider,
            m.OhlcvBar.ts >= session_open,
        )
        .order_by(m.OhlcvBar.instrument_id, m.OhlcvBar.ts)
    ):
        t = ts.astimezone(UTC)
        px_series[iid].append((t, float(close)))
        vol_series[iid].append((t, int(vol or 0)))

    spot_series = [
        (ts.astimezone(UTC), float(close))
        for ts, close in db.execute(
            select(m.OhlcvBar.ts, m.OhlcvBar.close)
            .where(
                m.OhlcvBar.instrument_id == underlying_id,
                m.OhlcvBar.timeframe == Timeframe.M1,
                m.OhlcvBar.provider == provider,
                m.OhlcvBar.ts >= session_open,
            )
            .order_by(m.OhlcvBar.ts)
        )
    ]

    legs = [
        OiLegSeries(
            strike=float(strike),
            option_type=otype.value if hasattr(otype, "value") else str(otype),
            oi=tuple(oi_series[iid]),
            premium=tuple(px_series[iid]),
            volume=tuple(vol_series[iid]),
        )
        for iid, strike, otype in opts
        if strike is not None
    ]
    cfg = (
        OiPulseConfig(recent_window_min=int(recent_window_min))
        if recent_window_min is not None
        else None
    )
    return build_oi_pulse(
        underlying_symbol=under.symbol,
        spot=spot,
        expiry=expiry,
        now=now,
        session_open=session_open,
        session_close=window.close_utc,  # trace stops at the bell, not "now"
        trace_window_up=trace_up,
        trace_window_down=trace_down,
        legs=legs,
        spot_series=tuple(spot_series),
        config=cfg,
    )


# ======================================================================================
# big OI movement — options only (docs/07 §4.22, docs/05 §11.4)
# ======================================================================================
#
# Re-shapes the OI-pulse strike ladder for one underlying's near expiry into the
# two lists a trader scans first: the strikes that ADDED the most open interest
# today and those that REDUCED it the most, each row carrying the session ΔOI,
# the last-15-min ΔOI, the buildup label, and moneyness. Options only.


#: moneyness bucketing by |strike − spot| as a fraction of spot
_MNY_ATM_PCT = 0.003  # within ±0.3 % of spot → ATM
_MNY_DEEP_PCT = 0.02  # beyond ±2 % → DEEP_ITM / DEEP_OTM
_MONEYNESS = ("DEEP_ITM", "ITM", "ATM", "OTM", "DEEP_OTM")


def _moneyness(strike: float, spot: float, option_type: str) -> str:
    if not spot:
        return "ATM"
    frac = abs(strike - spot) / spot
    if frac <= _MNY_ATM_PCT:
        return "ATM"
    in_the_money = (strike < spot) if option_type == "CE" else (strike > spot)
    deep = frac > _MNY_DEEP_PCT
    if in_the_money:
        return "DEEP_ITM" if deep else "ITM"
    return "DEEP_OTM" if deep else "OTM"


def _oi_mover_entry(strike: float, leg, spot: float) -> dict:
    diff = strike - spot
    mny = _moneyness(strike, spot, leg.option_type)
    return {
        "strike": strike,
        "option_type": leg.option_type,  # CE | PE
        "moneyness": mny,
        "dist_from_spot": round(diff, 2),
        "oi": leg.oi,
        "oi_at_open": leg.oi_at_open,
        "oi_change_session": leg.oi_change_session,
        "oi_change_session_pct": leg.oi_change_session_pct,
        "oi_change_recent": leg.oi_change_recent,
        "ltp": leg.ltp,
        "price_change_session_pct": leg.price_change_session_pct,
        "price_change_recent_pct": leg.price_change_recent_pct,
        # positioning over the SESSION — matches the list this row is in (added / reduced).
        # LONG_BUILDUP | SHORT_BUILDUP | LONG_UNWINDING | SHORT_COVERING | INDETERMINATE | NO_DATA
        "buildup": leg.buildup_session,
        # positioning over just the last `recent_window_min` — shown when it diverges
        # from the session read ("built all morning, now unwinding")
        "buildup_now": leg.buildup,
        "crowded": leg.crowded,
    }


def oi_movers(
    db: Session,
    underlying_id: int,
    *,
    top: int = 15,
    recent_window_min: int = 15,
    moneyness: set[str] | None = None,
    provider: str | None = None,
):
    """The biggest OI adds / drops across the near-expiry option strikes for
    ``underlying_id`` (docs/05 §11.4). Built on ``oi_pulse``. Options only.

    ``recent_window_min`` is the time band for the `Δ recent` column (3 / 5 / 10
    / 15). ``moneyness`` restricts to those buckets (``DEEP_ITM`` / ``ITM`` /
    ``ATM`` / ``OTM`` / ``DEEP_OTM``) before the top-N split. Returns ``None`` if
    the underlying has no options / no spot."""
    pulse = oi_pulse(db, underlying_id, provider=provider, recent_window_min=recent_window_min)
    if pulse is None:
        return None

    want = {x.upper() for x in moneyness} if moneyness else None
    entries: list[dict] = []
    for r in pulse.rows:
        for leg in (r.call, r.put):
            if leg is None:
                continue
            e = _oi_mover_entry(r.strike, leg, pulse.spot)
            if want is None or e["moneyness"] in want:
                entries.append(e)

    added = sorted(
        (e for e in entries if e["oi_change_session"] > 0),
        key=lambda e: -e["oi_change_session"],
    )[: max(1, top)]
    reduced = sorted(
        (e for e in entries if e["oi_change_session"] < 0),
        key=lambda e: e["oi_change_session"],
    )[: max(1, top)]

    return {
        "underlying_id": underlying_id,
        "underlying_symbol": pulse.underlying_symbol,
        "spot": pulse.spot,
        "expiry": pulse.expiry,
        "as_of": pulse.as_of,
        "session_open": pulse.session_open,
        "recent_window_min": int(recent_window_min),
        "moneyness_filter": sorted(want) if want else [],
        "pcr_oi_now": pulse.pcr_oi_now,
        "max_pain_now": pulse.max_pain_now,
        "support_strike": pulse.support_strike,
        "resistance_strike": pulse.resistance_strike,
        "crowded_side": pulse.crowded_side,
        "net_ce_oi_change": pulse.net_ce_oi_change,
        "net_pe_oi_change": pulse.net_pe_oi_change,
        "top": top,
        "added": added,
        "reduced": reduced,
        "oi_pulse_version": pulse.oi_pulse_version,
    }


# ======================================================================================
# daily digest (docs/07 §4.12)
# ======================================================================================

_DIGEST_SQL = """
    with d1 as (
        select b.ts::date                       as d,
               b.open, b.high, b.low, b.close,
               lag(b.close) over w              as prev_close,
               lag(b.high)  over w              as pdh,
               lag(b.low)   over w              as pdl
        from ohlcv_bars b
        where b.instrument_id = :iid and b.timeframe = 'D1' and b.provider = :provider
        window w as (order by b.ts)
    )
    select d1.d, d1.open, d1.high, d1.low, d1.close, d1.prev_close, d1.pdh, d1.pdl,
           mp.profile_shape, mp.poc, mp.vah, mp.val, mp.ib_high, mp.ib_low,
           mp.is_session_complete,
           mp.events -> 'day_type' ->> 'day_type' as day_type
    from d1
    left join market_profile_sessions mp
      on mp.instrument_id = :iid and mp.profile_type = 'TPO' and mp.session_date = d1.d
    where d1.prev_close is not null and d1.prev_close > 0
    order by d1.d
"""

_DIGEST_SORT = {"d": "d", "change": "change_pct", "range": "range_pct", "gap": "gap_pct"}

#: D1-only day-type proxy (docs/07 §4.12). Labels reuse the Market-Profile
#: ``MPDayType`` vocabulary so the digest's `day_type` column reads consistently
#: whether it came from the real TPO session or this OHLC classification. This is
#: a *reporting* proxy only — the MP event engine still honours docs/14 dec. 5
#: (no D1 proxy there; `INSUFFICIENT_DATA` before the 2022 M5 floor).
_D1_WIDE, _D1_NARROW = 1.25, 0.75


def _d1_day_type(
    o: float, h: float, lo: float, c: float, pdh: float, pdl: float, avg_range: float | None
) -> tuple[str, float | None, float | None]:
    rng = h - lo
    if rng <= 0:
        return "UNDETERMINED", None, None
    close_pos = (c - lo) / rng  # 0 = closed on the low, 1 = closed on the high
    rr = (rng / avg_range) if avg_range else None
    broke_h, broke_l = h > pdh, lo < pdl
    inside = h <= pdh and lo >= pdl
    wide = rr is not None and rr >= _D1_WIDE
    narrow = rr is not None and rr <= _D1_NARROW

    if wide and close_pos >= 0.70 and broke_h and not broke_l:
        return "TREND_UP", close_pos, rr
    if wide and close_pos <= 0.30 and broke_l and not broke_h:
        return "TREND_DOWN", close_pos, rr
    if broke_h and broke_l:
        return ("NEUTRAL_EXTREME" if 0.35 <= close_pos <= 0.65 else "NEUTRAL"), close_pos, rr
    if inside and narrow:
        return "RANGE", close_pos, rr
    if inside:
        return "NORMAL_VARIATION", close_pos, rr
    if wide:
        return "LARGE_RANGE", close_pos, rr
    return "NORMAL", close_pos, rr


def daily_digest(
    db: Session,
    instrument_id: int,
    *,
    start=None,
    end=None,
    sort: str = "-d",
    limit: int = 250,
    offset: int = 0,
    gap_min_pct: float | None = None,
    gap_max_pct: float | None = None,
    chg_min_pct: float | None = None,
    chg_max_pct: float | None = None,
) -> dict | None:
    """One row per trading day for ``instrument_id``: D1 OHLC, prev-day-high /
    prev-day-low break flags, a **D1 day-type** classified from the candle
    (:func:`_d1_day_type`) plus `close_range_pos` / `d1_range_ratio`, and the
    day's real **TPO profile** (`profile_shape`, `day_type`, POC/VAH/VAL/IB)
    where a ``market_profile_sessions`` row exists (null otherwise). Pure DB
    read.

    ``gap_min_pct``/``gap_max_pct`` and ``chg_min_pct``/``chg_max_pct`` filter
    on `gap_pct` (open vs prior close) and `change_pct` (close vs prior close),
    inclusive bounds, any combination — e.g. a "gapped up but faded to close
    down" study: `gap_min_pct=0.5, chg_max_pct=-0.5`. The rolling 14-day range
    average (`d1_range_ratio`) is still computed over *every* day in date
    order regardless of the gap/change filter, so filtered-out days still
    contribute to it — only which rows are *returned* changes."""
    from sqlalchemy import text as _text

    from app.config import get_settings

    inst = db.get(m.Instrument, instrument_id)
    if inst is None:
        return None
    desc = sort.startswith("-")
    token = sort[1:] if desc else sort
    if token not in _DIGEST_SORT:
        raise ValueError(f"unknown sort key {sort!r}; allowed: {sorted(_DIGEST_SORT)}")

    raw = (
        db.execute(
            _text(_DIGEST_SQL),
            {"iid": instrument_id, "provider": get_settings().active_provider},
        )
        .mappings()
        .all()
    )

    from collections import deque

    recent_ranges: deque[float] = deque(maxlen=14)  # trailing D1 ranges, prior days only
    rows: list[dict] = []
    for r in raw:  # ascending by date — keep the rolling window continuous
        d = r["d"]
        o, h, lo, c = (float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]))
        rng = h - lo
        avg_range = (sum(recent_ranges) / len(recent_ranges)) if recent_ranges else None
        recent_ranges.append(rng)  # append AFTER, so avg_range is of prior days
        if (start and d < start) or (end and d > end):
            continue
        pc, pdh, pdl = float(r["prev_close"]), float(r["pdh"]), float(r["pdl"])
        pdh_broken, pdl_broken = h > pdh, lo < pdl
        d1_type, close_pos, range_ratio = _d1_day_type(o, h, lo, c, pdh, pdl, avg_range)
        vah = float(r["vah"]) if r["vah"] is not None else None
        val = float(r["val"]) if r["val"] is not None else None
        poc = float(r["poc"]) if r["poc"] is not None else None
        cvv = cvp = None
        if vah is not None and val is not None:
            cvv = "ABOVE" if c > vah else "BELOW" if c < val else "INSIDE"
        if poc is not None:
            cvp = "ABOVE" if c > poc else "BELOW" if c < poc else "AT"
        gap_pct = round((o - pc) / pc * 100.0, 3)
        change_pct = round((c - pc) / pc * 100.0, 3)
        if gap_min_pct is not None and gap_pct < gap_min_pct:
            continue
        if gap_max_pct is not None and gap_pct > gap_max_pct:
            continue
        if chg_min_pct is not None and change_pct < chg_min_pct:
            continue
        if chg_max_pct is not None and change_pct > chg_max_pct:
            continue
        rows.append(
            {
                "d": d.isoformat(),
                "weekday": d.strftime("%A"),
                "open": round(o, 4),
                "high": round(h, 4),
                "low": round(lo, 4),
                "close": round(c, 4),
                "prev_close": round(pc, 4),
                "change_pct": change_pct,
                "range_pct": round((h - lo) / pc * 100.0, 3),
                "gap_pct": gap_pct,
                "pdh": round(pdh, 4),
                "pdl": round(pdl, 4),
                "pdh_broken": pdh_broken,
                "pdl_broken": pdl_broken,
                "pdh_close_above": c > pdh,
                "pdl_close_below": c < pdl,
                "inside_day": h <= pdh and lo >= pdl,
                "outside_day": pdh_broken and pdl_broken,
                "range_type": (
                    "OUTSIDE"
                    if (pdh_broken and pdl_broken)
                    else "PDH_BREAK" if pdh_broken else "PDL_BREAK" if pdl_broken else "INSIDE"
                ),
                "profile_shape": r["profile_shape"],
                "day_type": r["day_type"],
                "d1_day_type": d1_type,
                "close_range_pos": round(close_pos, 4) if close_pos is not None else None,
                "d1_range_ratio": round(range_ratio, 3) if range_ratio is not None else None,
                "poc": round(poc, 4) if poc is not None else None,
                "vah": round(vah, 4) if vah is not None else None,
                "val": round(val, 4) if val is not None else None,
                "ib_high": round(float(r["ib_high"]), 4) if r["ib_high"] is not None else None,
                "ib_low": round(float(r["ib_low"]), 4) if r["ib_low"] is not None else None,
                "close_vs_value": cvv,
                "close_vs_poc": cvp,
                "profile_complete": r["is_session_complete"],
            }
        )

    rows.sort(key=lambda x: x[_DIGEST_SORT[token]], reverse=desc)
    n = len(rows)
    with_profile = sum(1 for x in rows if x["profile_shape"] is not None)
    d1_counts: dict[str, int] = {}
    for x in rows:
        d1_counts[x["d1_day_type"]] = d1_counts.get(x["d1_day_type"], 0) + 1
    summary = {
        "days": n,
        "pdh_breaks": sum(1 for x in rows if x["pdh_broken"]),
        "pdl_breaks": sum(1 for x in rows if x["pdl_broken"]),
        "inside_days": sum(1 for x in rows if x["inside_day"]),
        "outside_days": sum(1 for x in rows if x["outside_day"]),
        "pdh_close_above": sum(1 for x in rows if x["pdh_close_above"]),
        "pdl_close_below": sum(1 for x in rows if x["pdl_close_below"]),
        "mean_range_pct": round(sum(x["range_pct"] for x in rows) / n, 3) if n else 0.0,
        "mean_gap_pct": round(sum(x["gap_pct"] for x in rows) / n, 3) if n else 0.0,
        "mean_change_pct": round(sum(x["change_pct"] for x in rows) / n, 3) if n else 0.0,
        "days_with_profile": with_profile,
        "d1_day_type_counts": dict(sorted(d1_counts.items(), key=lambda kv: -kv[1])),
    }
    page = rows[offset : offset + limit]
    return {
        "instrument_id": instrument_id,
        "contract_key": inst.contract_key,
        "symbol": inst.symbol,
        "first": min((x["d"] for x in rows), default=None),
        "last": max((x["d"] for x in rows), default=None),
        "total": n,
        "limit": limit,
        "offset": offset,
        "sort": sort,
        "gap_min_pct": gap_min_pct,
        "gap_max_pct": gap_max_pct,
        "chg_min_pct": chg_min_pct,
        "chg_max_pct": chg_max_pct,
        "summary": summary,
        "items": page,
    }


def market_board(db: Session) -> list[dict]:
    """A compact data-first board for the dashboard (docs/08 §4.1): every tracked
    INDEX / FUTURE with its latest price, today's move, open interest and the
    M5 / H1 / D1 labels. Pure DB read — no provider call. Options are excluded
    (they belong to the option chain, not a directional board)."""

    insts = list(
        db.execute(
            select(m.Instrument)
            .where(
                m.Instrument.is_tracked.is_(True),
                m.Instrument.is_active.is_(True),
                m.Instrument.instrument_type.in_([InstrumentType.INDEX, InstrumentType.FUTURE]),
            )
            .order_by(m.Instrument.instrument_type, m.Instrument.contract_key)
        ).scalars()
    )
    if not insts:
        return []
    ids = [i.id for i in insts]

    # freshest price: newest M1 (fall back to M5) bar per instrument
    last_bar: dict[int, tuple] = {}
    for tf in (Timeframe.M1, Timeframe.M5):
        rows = db.execute(
            select(
                m.OhlcvBar.instrument_id,
                m.OhlcvBar.close,
                m.OhlcvBar.ts,
            )
            .where(m.OhlcvBar.instrument_id.in_(ids), m.OhlcvBar.timeframe == tf)
            .order_by(m.OhlcvBar.instrument_id, m.OhlcvBar.ts.desc())
            .distinct(m.OhlcvBar.instrument_id)
        ).all()
        for iid, close, ts in rows:
            last_bar.setdefault(iid, (close, ts))

    # today's D1 (open/high/low/close) + previous D1 close
    rn = (
        func.row_number()
        .over(partition_by=m.OhlcvBar.instrument_id, order_by=m.OhlcvBar.ts.desc())
        .label("rn")
    )
    d1_rows = db.execute(
        select(
            m.OhlcvBar.instrument_id,
            m.OhlcvBar.open,
            m.OhlcvBar.high,
            m.OhlcvBar.low,
            m.OhlcvBar.close,
            m.OhlcvBar.ts,
            rn,
        )
        .where(m.OhlcvBar.instrument_id.in_(ids), m.OhlcvBar.timeframe == Timeframe.D1)
        .order_by(m.OhlcvBar.instrument_id, m.OhlcvBar.ts.desc())
    ).all()
    today_d1: dict[int, tuple] = {}
    prev_close: dict[int, float] = {}
    for iid, o, h, low, c, ts, r in d1_rows:
        if r == 1:
            today_d1[iid] = (o, h, low, c, ts)
        elif r == 2:
            prev_close[iid] = float(c)

    # latest OI (futures)
    oi_rows = db.execute(
        select(m.OpenInterest.instrument_id, m.OpenInterest.oi, m.OpenInterest.ts)
        .where(m.OpenInterest.instrument_id.in_(ids))
        .order_by(m.OpenInterest.instrument_id, m.OpenInterest.ts.desc())
        .distinct(m.OpenInterest.instrument_id)
    ).all()
    latest_oi = {iid: (int(oi), ts) for iid, oi, ts in oi_rows}

    # history coverage: earliest / latest bar + D1 bar count, per timeframe
    coverage: dict[tuple[int, str], tuple] = {}
    for iid, tf, mn, mx, cnt in db.execute(
        select(
            m.OhlcvBar.instrument_id,
            m.OhlcvBar.timeframe,
            func.min(m.OhlcvBar.ts),
            func.max(m.OhlcvBar.ts),
            func.count(),
        )
        .where(
            m.OhlcvBar.instrument_id.in_(ids),
            m.OhlcvBar.timeframe.in_([Timeframe.D1, Timeframe.M1]),
        )
        .group_by(m.OhlcvBar.instrument_id, m.OhlcvBar.timeframe)
    ):
        coverage[(iid, tf.value)] = (mn, mx, cnt)

    # D1 + H1 + M5 labels (analysis is secondary here, but a chip is free)
    labels: dict[tuple[int, str], tuple[str, float]] = {}
    for row in db.execute(
        select(
            m.CurrentSignalScore.instrument_id,
            m.CurrentSignalScore.timeframe,
            m.CurrentSignalScore.effective_label,
            m.CurrentSignalScore.composite_score,
        ).where(
            m.CurrentSignalScore.instrument_id.in_(ids),
            m.CurrentSignalScore.timeframe.in_([Timeframe.D1, Timeframe.H1, Timeframe.M5]),
        )
    ):
        labels[(row.instrument_id, row.timeframe.value)] = (
            row.effective_label.value,
            float(row.composite_score),
        )

    now = datetime.now(tz=UTC)
    out: list[dict] = []
    for i in insts:
        lp, lts = last_bar.get(i.id, (None, None))
        lp = float(lp) if lp is not None else None
        d1 = today_d1.get(i.id)
        pc = prev_close.get(i.id)
        day_open = float(d1[0]) if d1 else None
        day_high = float(d1[1]) if d1 else None
        day_low = float(d1[2]) if d1 else None
        ref = pc if pc is not None else day_open
        chg = ((lp - ref) / ref * 100.0) if (lp is not None and ref) else None
        rng = (
            (day_high - day_low) / ref * 100.0
            if (d1 and ref and day_high is not None and day_low is not None)
            else None
        )
        oi = latest_oi.get(i.id)
        d1l = labels.get((i.id, "D1"))
        h1l = labels.get((i.id, "H1"))
        m5l = labels.get((i.id, "M5"))
        d1c = coverage.get((i.id, "D1"))
        m1c = coverage.get((i.id, "M1"))
        d1_through = d1c[1].astimezone(UTC).date() if d1c else None
        # heuristic: D1 is "current" if its last bar is within 4 days (covers a weekend)
        history_ok = bool(d1_through and (now.date() - d1_through).days <= 4)
        out.append(
            {
                "instrument_id": i.id,
                "contract_key": i.contract_key,
                "symbol": i.symbol,
                "instrument_type": i.instrument_type.value,
                "expiry_date": i.expiry_date.isoformat() if i.expiry_date else None,
                "d1_from": d1c[0].astimezone(UTC).date().isoformat() if d1c else None,
                "d1_through": d1_through.isoformat() if d1_through else None,
                "d1_bars": d1c[2] if d1c else None,
                "m1_from": m1c[0].astimezone(UTC).date().isoformat() if m1c else None,
                "m1_through": m1c[1].astimezone(UTC).date().isoformat() if m1c else None,
                "history_ok": history_ok,
                "last_price": lp,
                "last_ts": lts.astimezone(UTC).isoformat() if lts else None,
                "staleness_seconds": (now - lts.astimezone(UTC)).total_seconds() if lts else None,
                "prev_close": pc,
                "day_open": day_open,
                "day_high": day_high,
                "day_low": day_low,
                "day_change_pct": round(chg, 3) if chg is not None else None,
                "day_range_pct": round(rng, 3) if rng is not None else None,
                "oi": oi[0] if oi else None,
                "oi_ts": oi[1].astimezone(UTC).isoformat() if oi else None,
                "label_d1": d1l[0] if d1l else None,
                "score_d1": d1l[1] if d1l else None,
                "label_h1": h1l[0] if h1l else None,
                "label_m5": m5l[0] if m5l else None,
            }
        )
    return out


def recent_m1_bar_age_seconds(db: Session) -> float | None:
    """Seconds since the newest M1 bar of any tracked instrument was ingested —
    a freshness proxy for both the REST cycle and the streamer (docs/02 §3.4).
    ``None`` if there are no M1 bars."""
    try:
        ts = db.execute(
            select(func.max(m.OhlcvBar.ingested_at)).where(m.OhlcvBar.timeframe == Timeframe.M1)
        ).scalar_one_or_none()
    except SQLAlchemyError:
        return None
    if ts is None:
        return None
    return (datetime.now(tz=UTC) - ts.astimezone(UTC)).total_seconds()


def instrument_quote(db: Session, instrument_id: int) -> dict | None:
    """Live REST snapshot for one instrument (docs/07 §4.10): full quote + (for
    an OPTION) live greeks, via the active provider. ``None`` if the instrument
    or its active provider map is missing. Provider errors propagate."""
    from app.config import get_settings
    from app.providers.factory import build_live_provider

    inst = get_instrument(db, instrument_id)
    if inst is None:
        return None
    settings = get_settings()
    maps = [
        x
        for x in provider_map_for(db, instrument_id)
        if x.provider == settings.active_provider and x.is_active
    ]
    if not maps:
        return None
    key = maps[0].provider_symbol

    provider, close = build_live_provider(settings)
    try:
        full = provider.fetch_full_quote([key]).get(key)
        greeks = (
            provider.fetch_option_greeks([key]).get(key)
            if inst.instrument_type is InstrumentType.OPTION
            else None
        )
    finally:
        close()
    return {
        "instrument_id": inst.id,
        "contract_key": inst.contract_key,
        "provider": settings.active_provider,
        "provider_symbol": key,
        "full": full,
        "greeks": greeks,
    }


# ======================================================================================
# Index constituents / weightage (docs/15, docs/07 §4.14)
# ======================================================================================


def index_constituents(
    db: Session,
    instrument_id: int,
    *,
    effective_date=None,
    include_beta: bool = False,
    lookback: int = 60,
    as_of_date=None,
):
    """Weightage-ordered constituent view for an INDEX (docs/15): weight +
    cumulative + sector + concentration always; day contribution + breadth when
    a quote is reachable per name; beta / correlation only when ``include_beta``
    (fetches ~``lookback`` D1 closes per name). ``None`` when the id is not an
    INDEX or no weights are seeded. Pure math in ``analytical_core.indices``.

    ``as_of_date`` swaps the live-quote read for a historical one: each name's
    (and the index's) D1 close on the last trading day on or before that date,
    vs. the prior close — the same "day contribution" analysis, replayed for a
    past session, entirely fetched on read (constituents aren't ingested).
    Raises ``ValueError`` if ``as_of_date`` is in the future."""
    from datetime import datetime, time, timedelta

    from analytical_core.indices import (
        ConstituentQuote,
        build_constituent_view,
    )
    from analytical_core.versioning import ALGO_VERSION
    from app.config import get_settings
    from app.indices.weights import INDEX_NAMES, weight_rows_for
    from app.ingestion.session import IST
    from app.providers.base import ProviderAuthError, ProviderError
    from app.providers.factory import build_live_provider

    if as_of_date is not None and as_of_date > datetime.now(tz=IST).date():
        raise ValueError("as_of_date cannot be in the future")

    inst = get_instrument(db, instrument_id)
    if inst is None or inst.instrument_type is not InstrumentType.INDEX:
        return None
    index_key = inst.contract_key
    rows, eff, prov_syms = weight_rows_for(db, index_key, effective_date=effective_date)
    if not rows:
        return None

    settings = get_settings()
    provider_name = settings.active_provider
    quotes: list[ConstituentQuote] = []
    history: dict[str, list[float]] = {}
    index_ltp = index_prev = None
    as_of = None
    source = "seed"
    idx_hist = None

    want = {sym: ps for sym, ps in prov_syms.items() if ps}
    idx_maps = [
        x
        for x in provider_map_for(db, instrument_id)
        if x.provider == provider_name and x.is_active
    ]
    idx_psym = idx_maps[0].provider_symbol if idx_maps else None

    if want or idx_psym:
        try:
            provider, close = build_live_provider(settings)
            try:
                if as_of_date is not None:
                    hist_end = datetime.combine(as_of_date, time.max, IST).astimezone(_utc())
                    span_days = max(lookback * 2 + 10, 40) if include_beta else 21
                    hist_start = hist_end - timedelta(days=span_days)

                    def _closes_on_or_before(ps: str) -> list[tuple[Any, float]]:
                        try:
                            bars = provider.fetch_ohlcv(ps, Timeframe.D1, hist_start, hist_end)
                        except ProviderError:
                            return []
                        by_date = sorted(
                            {b.ts.astimezone(IST).date(): float(b.close) for b in bars}.items()
                        )
                        return [(d, c) for d, c in by_date if d <= as_of_date]

                    resolved_date = None
                    for sym, ps in want.items():
                        closes = _closes_on_or_before(ps)
                        if not closes:
                            continue
                        ltp = closes[-1][1]
                        pc = closes[-2][1] if len(closes) >= 2 else None
                        quotes.append(ConstituentQuote(symbol=sym, ltp=ltp, prev_close=pc))
                        if include_beta:
                            cl = [c for _, c in closes][-(lookback + 1) :]
                            if len(cl) >= 3:
                                history[sym] = cl
                    if idx_psym:
                        closes = _closes_on_or_before(idx_psym)
                        if closes:
                            index_ltp = closes[-1][1]
                            index_prev = closes[-2][1] if len(closes) >= 2 else None
                            resolved_date = closes[-1][0]
                            if include_beta:
                                idx_hist = [c for _, c in closes][-(lookback + 1) :]
                    as_of = (resolved_date or as_of_date).isoformat()
                else:
                    keys = list(want.values()) + ([idx_psym] if idx_psym else [])
                    fq = provider.fetch_full_quote(keys)

                    def _ltp_prev(fqx) -> tuple[float | None, float | None]:
                        # prev close from net_change when we have it (survives after
                        # the close, when `close` becomes today's close == ltp)
                        ltp = float(fqx.last_price) if fqx.last_price is not None else None
                        nc = float(fqx.net_change) if fqx.net_change is not None else None
                        if ltp is not None and nc is not None:
                            return ltp, ltp - nc
                        return ltp, (float(fqx.close) if fqx.close is not None else None)

                    for sym, ps in want.items():
                        q = fq.get(ps)
                        if q is None:
                            continue
                        ltp, pc = _ltp_prev(q)
                        quotes.append(ConstituentQuote(symbol=sym, ltp=ltp, prev_close=pc))
                        if q.ts is not None and as_of is None:
                            as_of = q.ts.isoformat()
                    if idx_psym and idx_psym in fq:
                        index_ltp, index_prev = _ltp_prev(fq[idx_psym])
                    if include_beta and want:
                        end = datetime.now(tz=_utc())
                        start = end - timedelta(days=max(lookback * 2 + 10, 40))
                        for sym, ps in want.items():
                            try:
                                bars = provider.fetch_ohlcv(ps, Timeframe.D1, start, end)
                            except ProviderError:
                                continue
                            cl = [float(b.close) for b in bars][-(lookback + 1) :]
                            if len(cl) >= 3:
                                history[sym] = cl
                        if idx_psym:
                            try:
                                ib = provider.fetch_ohlcv(idx_psym, Timeframe.D1, start, end)
                                idx_hist = [float(b.close) for b in ib][-(lookback + 1) :]
                            except ProviderError:
                                idx_hist = None
            finally:
                close()
            # "seed" unless the provider actually gave us per-name quotes
            source = provider_name if quotes else "seed"
        except (ProviderError, ProviderAuthError, RuntimeError):
            quotes = []
            history = {}
            idx_hist = None

    view = build_constituent_view(
        index_symbol=INDEX_NAMES.get(index_key, inst.symbol),
        algo_version=ALGO_VERSION,
        weight_rows=rows,
        weights_effective_date=eff.isoformat() if eff else None,
        source=source,
        quotes=quotes or None,
        as_of=as_of,
        index_ltp=index_ltp,
        index_prev_close=index_prev,
        history=history or None,
        index_history=idx_hist,
        beta_lookback=lookback if (include_beta and history) else None,
    )
    return view


# ======================================================================================
# Top-N constituents — levels + indicators, fetched on read (docs/07 §4.20, docs/15)
# ======================================================================================
#
# For the top-N index members by weight: prev-day CPR / pivots, the 52-week
# range, RSI (D1 + H1), Bollinger (D1) and the MA trend (EMA20/50, 50/200 SMA
# cross) — every candle fetched live from the provider on read (constituents are
# not tracked / not ingested). Heavy (2 provider calls per name); cache hard.
# Descriptive — no signal, no BUY/SELL.

_CONSTITUENT_LEVELS_VERSION = "0.1.0"


def _pos_word(x: float, ref: float, eps: float) -> str:
    return "ABOVE" if x > ref + eps else "BELOW" if x < ref - eps else "AT"


def constituent_levels(db: Session, index_id: int, *, n: int = 10):
    """Levels + indicators for the top-``n`` constituents by weight (docs/15).
    Fetches ~14 months of D1 and ~10 days of H1 per name from the live provider,
    runs the pure indicators, and returns one row per stock. ``None`` if the id
    is not an INDEX or no weights are seeded."""
    from datetime import datetime, timedelta

    from analytical_core.enums import InstrumentType, Timeframe
    from analytical_core.indicators import bollinger, golden_cross, rsi
    from analytical_core.indicators._common import ema_series, rolling_sma
    from analytical_core.pivots import compute_pivots, width_band
    from analytical_core.series import OHLCVSeries
    from app.config import get_settings
    from app.indices.weights import weight_rows_for
    from app.ingestion.aggregation import aggregate_m1
    from app.providers.base import ProviderAuthError, ProviderError
    from app.providers.factory import build_live_provider

    inst = get_instrument(db, index_id)
    if inst is None or inst.instrument_type is not InstrumentType.INDEX:
        return None
    rows, eff, prov_syms = weight_rows_for(db, inst.contract_key)
    if not rows:
        return None

    n = max(1, min(int(n), 20))
    top = sorted(rows, key=lambda r: r.weight_pct, reverse=True)[:n]
    now = datetime.now(tz=_utc())
    d1_start = now - timedelta(days=430)
    # Upstox serves only D1 / M1 — the intraday (H1) read is aggregated from a
    # few sessions of M1 on the fly.
    m1_start = now - timedelta(days=6)

    def _series(bars, tf: Timeframe, *, min_bars: int = 20) -> OHLCVSeries | None:
        bars = sorted(bars, key=lambda b: b.ts)
        if len(bars) < min_bars:
            return None
        return OHLCVSeries(
            timeframe=tf,
            ts=tuple(b.ts.astimezone(_utc()) for b in bars),
            open=tuple(float(b.open) for b in bars),
            high=tuple(float(b.high) for b in bars),
            low=tuple(float(b.low) for b in bars),
            close=tuple(float(b.close) for b in bars),
            volume=tuple(int(b.volume) for b in bars),
            is_final=tuple(bool(b.is_final) for b in bars),
            expected_grid_len=len(bars),
        )

    def _ok(res):
        return res.values if res.status.value == "OK" else {}

    stocks: list[dict] = []
    errors: list[dict] = []
    provider = None
    close_provider = None
    try:
        provider, close_provider = build_live_provider(get_settings())
    except (ProviderError, ProviderAuthError, RuntimeError) as exc:
        return {
            "index_id": index_id,
            "contract_key": inst.contract_key,
            "weights_effective_date": eff.isoformat() if eff else None,
            "generated_at": now.isoformat(),
            "n": n,
            "stocks": [],
            "errors": [{"symbol": "*", "reason": f"provider unavailable: {exc}"}],
            "constituent_levels_version": _CONSTITUENT_LEVELS_VERSION,
        }

    try:
        cum = 0.0
        for rank, wr in enumerate(top, start=1):
            cum += wr.weight_pct
            psym = prov_syms.get(wr.symbol)
            if not psym:
                errors.append({"symbol": wr.symbol, "reason": "no provider mapping"})
                continue
            try:
                d1_bars = provider.fetch_ohlcv(psym, Timeframe.D1, d1_start, now)
            except ProviderError as exc:
                errors.append({"symbol": wr.symbol, "reason": str(exc)})
                continue

            d1 = _series(d1_bars, Timeframe.D1)
            if d1 is None:
                errors.append({"symbol": wr.symbol, "reason": "not enough D1 history"})
                continue

            h1 = None
            try:
                m1_bars = provider.fetch_ohlcv(psym, Timeframe.M1, m1_start, now)
                h1_bars = aggregate_m1(m1_bars, Timeframe.H1).bars if m1_bars else []
                h1 = _series(h1_bars, Timeframe.H1, min_bars=15)
            except ProviderError:
                pass  # intraday read is best-effort

            closes = list(d1.close)
            last = float(h1.close[-1]) if h1 is not None else closes[-1]
            eps = last * 0.0005

            # prev completed D1 → today's pivot / CPR
            d1_sorted = sorted(d1_bars, key=lambda b: b.ts)
            pv_src = d1_sorted[-2] if len(d1_sorted) >= 2 else d1_sorted[-1]
            pl = compute_pivots(float(pv_src.high), float(pv_src.low), float(pv_src.close))

            # 52-week range
            w = d1_sorted[-252:]
            hi52 = max(float(b.high) for b in w)
            lo52 = min(float(b.low) for b in w)
            span = hi52 - lo52

            rsi_d1 = _ok(rsi(d1))
            rsi_h1 = _ok(rsi(h1)) if h1 is not None else {}
            bb = _ok(bollinger(d1))
            gc = _ok(golden_cross(d1, instrument_type=InstrumentType.INDEX))

            ema20 = ema_series(closes, 20)[-1]
            ema50 = ema_series(closes, 50)[-1]
            sma50 = rolling_sma(closes, 50)[-1]
            sma200 = rolling_sma(closes, 200)[-1]

            cross_state = (
                "ABOVE"
                if sma50 is not None and sma200 is not None and sma50 > sma200
                else "BELOW" if sma50 is not None and sma200 is not None else None
            )
            close_vs_p = _pos_word(last, pl.pivot, eps)
            rng_pos = ((last - lo52) / span) if span else None

            hint_bits = [
                f"{close_vs_p.lower()} pivot",
                (f"RSI {rsi_d1['rsi']:.0f} {str(rsi_d1['state']).lower()}" if rsi_d1 else ""),
                (
                    f"50{'>' if cross_state == 'ABOVE' else '<'}200"
                    if cross_state and sma50 and sma200
                    else ""
                ),
                (f"{rng_pos * 100:.0f}% of 52w" if rng_pos is not None else ""),
            ]
            hint = " · ".join(b for b in hint_bits if b)

            stocks.append(
                {
                    "rank": rank,
                    "symbol": wr.symbol,
                    "name": wr.name,
                    "sector": wr.sector,
                    "weight_pct": round(wr.weight_pct, 3),
                    "cumulative_weight_pct": round(cum, 2),
                    "last_price": round(last, 2),
                    "prev_close": round(float(pv_src.close), 2),
                    "day_change_pct": (
                        round((last - float(pv_src.close)) / float(pv_src.close) * 100.0, 2)
                        if pv_src.close
                        else None
                    ),
                    "pivot": {
                        "p": round(pl.pivot, 2),
                        "tc": round(pl.cpr_top, 2),
                        "bc": round(pl.cpr_bottom, 2),
                        "r1": round(pl.r1, 2),
                        "r2": round(pl.r2, 2),
                        "r3": round(pl.r3, 2),
                        "s1": round(pl.s1, 2),
                        "s2": round(pl.s2, 2),
                        "s3": round(pl.s3, 2),
                        "cpr_width_pct": round(pl.cpr_width_pct, 3),
                        "width_band": width_band(pl.cpr_width_pct).value,
                        "close_vs_pivot": close_vs_p,
                    },
                    "range52": {
                        "high": round(hi52, 2),
                        "low": round(lo52, 2),
                        "pct_from_high": round((last - hi52) / hi52 * 100.0, 2) if hi52 else None,
                        "pct_from_low": round((last - lo52) / lo52 * 100.0, 2) if lo52 else None,
                        "position": round(rng_pos, 3) if rng_pos is not None else None,
                    },
                    "rsi_d1": (
                        {"value": rsi_d1["rsi"], "state": rsi_d1["state"]} if rsi_d1 else None
                    ),
                    "rsi_h1": (
                        {"value": rsi_h1["rsi"], "state": rsi_h1["state"]} if rsi_h1 else None
                    ),
                    "bollinger_d1": (
                        {
                            "pct_b": bb.get("percent_b"),
                            "position": bb.get("position"),
                            "squeeze": bb.get("squeeze"),
                        }
                        if bb
                        else None
                    ),
                    "ma": {
                        "ema20": round(ema20, 2) if ema20 is not None else None,
                        "ema50": round(ema50, 2) if ema50 is not None else None,
                        "sma50": round(sma50, 2) if sma50 is not None else None,
                        "sma200": round(sma200, 2) if sma200 is not None else None,
                        "price_vs_ema20": (
                            _pos_word(last, ema20, eps) if ema20 is not None else None
                        ),
                        "price_vs_ema50": (
                            _pos_word(last, ema50, eps) if ema50 is not None else None
                        ),
                        "cross_state": cross_state,
                        "cross_type": gc.get("cross_type") if gc else None,
                        "bars_since_cross": gc.get("bars_since_cross") if gc else None,
                        "recent_cross": bool(gc.get("recent")) if gc else False,
                    },
                    "hint": hint,
                }
            )
    finally:
        if close_provider:
            close_provider()

    return {
        "index_id": index_id,
        "contract_key": inst.contract_key,
        "weights_effective_date": eff.isoformat() if eff else None,
        "generated_at": now.isoformat(),
        "n": n,
        "stocks": stocks,
        "errors": errors,
        "constituent_levels_version": _CONSTITUENT_LEVELS_VERSION,
    }


# ======================================================================================
# Key levels — last two sessions' profiles + proximity alert (docs/05 §10.12)
# ======================================================================================

#: default proximity bands (points) by contract_key prefix — BANKNIFTY / SENSEX
#: move several times a NIFTY point, so a wider band. Overridable per request.
_KEY_LEVEL_BANDS: dict[str, tuple[float, float, float]] = {
    "NIFTY": (15.0, 30.0, 45.0),
    "BANKNIFTY": (40.0, 80.0, 120.0),
    "SENSEX": (40.0, 80.0, 120.0),
}
_KEY_LEVEL_BANDS_DEFAULT = (15.0, 30.0, 45.0)


def _default_key_bands(contract_key: str) -> tuple[float, float, float]:
    for pfx, b in _KEY_LEVEL_BANDS.items():
        if contract_key.upper().startswith(pfx):
            return b
    return _KEY_LEVEL_BANDS_DEFAULT


_KEY_LEVEL_SESS_SQL = """
    select mp.session_date, mp.profile_shape, mp.poc, mp.vah, mp.val,
           mp.ib_high, mp.ib_low, mp.session_high, mp.session_low, mp.close,
           mp.is_session_complete,
           mp.events -> 'day_type' ->> 'day_type' as day_type
    from market_profile_sessions mp
    where mp.instrument_id = :iid and mp.profile_type = 'TPO'
      and mp.is_session_complete is true
    order by mp.session_date desc
    limit 2
"""


def key_levels(
    db: Session,
    instrument_id: int,
    *,
    bands: tuple[float, float, float] | None = None,
    recent_m5: int = 12,
):
    """Last two completed sessions' Market-Profile levels + a proximity read of
    the latest price against them (docs/05 §10.12). Pure math in
    ``analytical_core.market_profile.build_key_levels``; this only fetches. Returns
    ``None`` if the id is unknown or fewer than one completed TPO session exists."""
    from datetime import timedelta

    from sqlalchemy import text as _text

    from analytical_core.market_profile import (
        Bands,
        LevelSession,
        RecentBar,
        build_key_levels,
    )

    inst = get_instrument(db, instrument_id)
    if inst is None:
        return None
    b3 = bands or _default_key_bands(inst.contract_key)

    rows = db.execute(_text(_KEY_LEVEL_SESS_SQL), {"iid": instrument_id}).mappings().all()
    if not rows:
        return None

    def _f(x) -> float | None:
        return None if x is None else float(x)

    sessions = [
        LevelSession(
            label=f"D-{i + 1}",
            date=r["session_date"].isoformat(),
            shape=r["profile_shape"],
            day_type=r["day_type"],
            poc=_f(r["poc"]),
            vah=_f(r["vah"]),
            val=_f(r["val"]),
            ib_high=_f(r["ib_high"]),
            ib_low=_f(r["ib_low"]),
            high=_f(r["session_high"]),
            low=_f(r["session_low"]),
            close=_f(r["close"]),
            complete=bool(r["is_session_complete"]),
        )
        for i, r in enumerate(rows)
    ]

    # latest price + recent M5 bars for the acceptance read
    now = datetime.now(tz=_utc())
    m5 = db.execute(
        select(m.OhlcvBar.high, m.OhlcvBar.low, m.OhlcvBar.close, m.OhlcvBar.ts)
        .where(
            m.OhlcvBar.instrument_id == instrument_id,
            m.OhlcvBar.timeframe == Timeframe.M5,
            m.OhlcvBar.ts >= now - timedelta(days=4),
        )
        .order_by(m.OhlcvBar.ts.desc())
        .limit(max(recent_m5, 1))
    ).all()
    if m5:
        last_price = float(m5[0][2])
        recent = [RecentBar(float(h), float(lo), float(c)) for h, lo, c, _ in reversed(m5)]
    else:
        d1 = db.execute(
            select(m.OhlcvBar.close)
            .where(
                m.OhlcvBar.instrument_id == instrument_id,
                m.OhlcvBar.timeframe == Timeframe.D1,
            )
            .order_by(m.OhlcvBar.ts.desc())
            .limit(1)
        ).scalar()
        if d1 is None:
            return None
        last_price = float(d1)
        recent = []

    view = build_key_levels(
        sessions,
        last_price=last_price,
        bands=Bands(*b3),
        recent=recent or None,
    )
    return {"instrument_id": instrument_id, "contract_key": inst.contract_key, **_dc_asdict(view)}


# ======================================================================================
# Multi-timeframe candle-pattern grid (docs/07 §4.17, docs/05 §9b)
# ======================================================================================
#
# 5m / 15m / 30m / 1h columns, the last N pattern hits per column (newest first).
# M5 / M15 / H1 read the stored aggregated bars; **M30 is folded on read** from
# M5 (session-open-anchored) because there is no M30 in the engine grid
# (decision 4). Computed on read, not persisted, not scored — descriptive only.

_CANDLE_GRID_VERSION = "0.1.0"
_CANDLE_GRID_TIMEFRAMES = ("M5", "M15", "M30", "H1")
_CANDLE_GRID_LOAD = 90  # bars per real timeframe — clears scan + trend + 3-bar context


@dataclass(frozen=True, slots=True)
class _GBar:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    is_final: bool


def _fold_m5_to_m30(m5_rows: list[_GBar]) -> list[_GBar]:
    """Session-open-anchored 30-minute fold of ascending M5 rows (docs/05 §3.5
    rule; 09:15–09:45, …, 15:15–15:30 partial)."""
    from app.ingestion.session import nse_session_window, trading_date_of

    if not m5_rows:
        return []
    step = timedelta(minutes=30)
    grace = timedelta(seconds=90)
    now = datetime.now(tz=_utc())

    by_date: dict[Any, list[_GBar]] = {}
    for r in m5_rows:
        by_date.setdefault(trading_date_of(r.ts), []).append(r)

    out: list[_GBar] = []
    for tdate in sorted(by_date):
        win = nse_session_window(tdate)
        slots: dict[int, list[_GBar]] = {}
        for r in by_date[tdate]:
            if not win.contains(r.ts):
                continue
            slots.setdefault(int((r.ts - win.open_utc) // step), []).append(r)
        for idx in sorted(slots):
            kids = sorted(slots[idx], key=lambda x: x.ts)
            start = win.open_utc + idx * step
            end = min(start + step, win.close_utc)
            out.append(
                _GBar(
                    ts=start,
                    open=kids[0].open,
                    high=max(k.high for k in kids),
                    low=min(k.low for k in kids),
                    close=kids[-1].close,
                    volume=sum(k.volume for k in kids),
                    is_final=all(k.is_final for k in kids) and now >= end + grace,
                )
            )
    return out


def _candles_grid_column(tf: str, bars: list[_GBar], limit: int) -> dict:
    from analytical_core.enums import Timeframe
    from analytical_core.indicators import candles
    from analytical_core.series import OHLCVSeries

    col: dict[str, Any] = {
        "timeframe": tf,
        "status": "INSUFFICIENT_DATA",
        "as_of_ts": None,
        "reason": None,
        "bias": None,
        "last_pattern": None,
        "last_bias": None,
        "last_strength": None,
        "last_bars_ago": None,
        "on_last_bar": False,
        "n_bullish": 0,
        "n_bearish": 0,
        "bars_scanned": 0,
        "patterns": [],
    }
    if not bars:
        col["reason"] = "no bars ingested for this timeframe"
        return col

    # candles() never inspects series.timeframe; M30 has no enum member, so tag
    # the synthetic grid with the nearest real member for typing only.
    tf_tag = Timeframe.M15 if tf == "M30" else Timeframe(tf)
    series = OHLCVSeries(
        timeframe=tf_tag,
        ts=tuple(b.ts.astimezone(_utc()) for b in bars),
        open=tuple(float(b.open) for b in bars),
        high=tuple(float(b.high) for b in bars),
        low=tuple(float(b.low) for b in bars),
        close=tuple(float(b.close) for b in bars),
        volume=tuple(int(b.volume) for b in bars),
        is_final=tuple(bool(b.is_final) for b in bars),
        expected_grid_len=len(bars),
    )
    res = candles(series)
    col["status"] = res.status.value
    col["as_of_ts"] = res.as_of_ts.isoformat() if res.as_of_ts else None
    v = res.values
    if res.status.value == "OK":
        for k in (
            "bias",
            "last_pattern",
            "last_bias",
            "last_strength",
            "last_bars_ago",
            "on_last_bar",
            "n_bullish",
            "n_bearish",
            "bars_scanned",
        ):
            col[k] = v[k]
        col["patterns"] = list(v["patterns"][: max(limit, 0)])
    else:
        col["reason"] = v.get("reason")
    return col


def candles_grid(db: Session, instrument_id: int, *, limit: int = 5):
    """Last ``limit`` major candlestick patterns per timeframe (5m/15m/30m/1h),
    newest first (docs/05 §9b). INDEX / FUTURE only — every column is
    ``NOT_APPLICABLE`` on an OPTION. Computed on read, not persisted, not scored.
    Returns ``None`` if the id is unknown."""
    from analytical_core.enums import InstrumentType, Timeframe

    inst = get_instrument(db, instrument_id)
    if inst is None:
        return None

    applicable = inst.instrument_type in (InstrumentType.INDEX, InstrumentType.FUTURE)

    def _load(tf: Timeframe) -> list[_GBar]:
        rows = db.execute(
            select(
                m.OhlcvBar.ts,
                m.OhlcvBar.open,
                m.OhlcvBar.high,
                m.OhlcvBar.low,
                m.OhlcvBar.close,
                m.OhlcvBar.volume,
                m.OhlcvBar.is_final,
            )
            .where(
                m.OhlcvBar.instrument_id == instrument_id,
                m.OhlcvBar.timeframe == tf,
            )
            .order_by(m.OhlcvBar.ts.desc())
            .limit(_CANDLE_GRID_LOAD)
        ).all()
        return [
            _GBar(
                ts=r.ts,
                open=float(r.open),
                high=float(r.high),
                low=float(r.low),
                close=float(r.close),
                volume=int(r.volume),
                is_final=bool(r.is_final),
            )
            for r in reversed(rows)
        ]

    m5_rows = _load(Timeframe.M5) if applicable else []
    columns: list[dict] = []
    for tf in _CANDLE_GRID_TIMEFRAMES:
        if not applicable:
            columns.append(
                {
                    **_candles_grid_column(tf, [], limit),
                    "status": "NOT_APPLICABLE",
                    "reason": "candlestick patterns run on INDEX / FUTURE only (docs/04 §4)",
                }
            )
            continue
        if tf == "M5":
            bars = m5_rows
        elif tf == "M30":
            bars = _fold_m5_to_m30(m5_rows)
        else:
            bars = _load(Timeframe(tf))
        columns.append(_candles_grid_column(tf, bars, limit))

    return {
        "instrument_id": instrument_id,
        "contract_key": inst.contract_key,
        "instrument_type": inst.instrument_type.value,
        "generated_at": datetime.now(tz=_utc()).isoformat(),
        "limit": limit,
        "columns": columns,
        "candles_grid_version": _CANDLE_GRID_VERSION,
    }


# ======================================================================================
# Golden Cross — one row per timeframe (docs/07 §4.19, docs/05 §7)
# ======================================================================================
#
# The 50 / 200 SMA cross state + the last cross (golden / death, bars ago) for
# 5m / 15m / 1h / 1D side by side — the same pure `golden_cross` indicator run
# per timeframe. Computed on read, not persisted, not scored. Descriptive.
#
# Also reads the fast/slow MAs as dynamic support/resistance: how far the last
# price sits from each (`dist_to_fast_pct` / `dist_to_slow_pct`), and flags
# `near_fast` / `near_slow` when within `golden_cross.near_ma_pct` (default
# 0.3%) — the "200 MA acting as support/resistance" alert.

_GC_GRID_VERSION = "0.2.0"  # 0.2.0: price-vs-MA proximity (support/resistance read, 2026-09-15)
_GC_GRID_TIMEFRAMES = ("M5", "M15", "H1", "D1")
_GC_GRID_LOAD = 280  # ≥ slow_period (200) + the cross-search window + headroom


def _gc_ma_proximity(
    last_price: float, fast: float | None, slow: float | None, near_pct: float
) -> dict:
    """Read the fast/slow MAs as dynamic support/resistance: how close is the
    last price to each, and is either "near" (within ``near_pct``)? Whichever
    MA is nearer (and within the band) is ``nearest_ma``; a MA below price
    reads as support, above as resistance — same vocabulary as the key-levels
    proximity read (docs/05 §10.12), just percentage-based since the two MAs
    span very different absolute scales across timeframes."""
    out = {
        "last_price": round(last_price, 4),
        "dist_to_fast_pct": None,
        "dist_to_slow_pct": None,
        "near_fast": False,
        "near_slow": False,
        "nearest_ma": None,
        "nearest_ma_side": None,
    }
    candidates = []
    for name, ma in (("fast", fast), ("slow", slow)):
        if ma is None or ma <= 0:
            continue
        dist_pct = (last_price - ma) / ma
        out[f"dist_to_{name}_pct"] = round(dist_pct, 6)
        near = abs(dist_pct) <= near_pct
        out[f"near_{name}"] = near
        if near:
            candidates.append((abs(dist_pct), name, dist_pct))
    if candidates:
        candidates.sort(key=lambda x: x[0])
        _, name, dist_pct = candidates[0]
        out["nearest_ma"] = name.upper()
        out["nearest_ma_side"] = "RESISTANCE" if dist_pct < 0 else "SUPPORT"
    return out


def _gc_grid_column(tf: str, bars: list, instrument_type, near_pct: float) -> dict:
    from analytical_core.enums import Timeframe
    from analytical_core.indicators import golden_cross
    from analytical_core.series import OHLCVSeries

    col: dict[str, Any] = {
        "timeframe": tf,
        "status": "INSUFFICIENT_DATA",
        "as_of_ts": None,
        "reason": None,
        "fast": None,
        "slow": None,
        "state": None,
        "cross_type": None,
        "cross_ts": None,
        "bars_since_cross": None,
        "separation": None,
        "recent": False,
        "provisional": False,
        "last_price": None,
        "dist_to_fast_pct": None,
        "dist_to_slow_pct": None,
        "near_fast": False,
        "near_slow": False,
        "nearest_ma": None,
        "nearest_ma_side": None,
    }
    if not bars:
        col["reason"] = "no bars ingested for this timeframe"
        return col
    series = OHLCVSeries(
        timeframe=Timeframe(tf),
        ts=tuple(b.ts.astimezone(_utc()) for b in bars),
        open=tuple(float(b.open) for b in bars),
        high=tuple(float(b.high) for b in bars),
        low=tuple(float(b.low) for b in bars),
        close=tuple(float(b.close) for b in bars),
        volume=tuple(int(b.volume) for b in bars),
        is_final=tuple(bool(b.is_final) for b in bars),
        expected_grid_len=len(bars),
    )
    res = golden_cross(series, instrument_type=instrument_type)
    col["status"] = res.status.value
    col["as_of_ts"] = res.as_of_ts.isoformat() if res.as_of_ts else None
    v = res.values
    if res.status.value == "OK":
        for k in (
            "fast",
            "slow",
            "state",
            "cross_type",
            "cross_ts",
            "bars_since_cross",
            "separation",
            "recent",
            "provisional",
        ):
            col[k] = v[k]
        col.update(_gc_ma_proximity(float(bars[-1].close), v["fast"], v["slow"], near_pct))
    else:
        col["reason"] = v.get("reason")
    return col


def golden_cross_grid(db: Session, instrument_id: int):
    """The 50 / 200 SMA golden-cross read for each of 5m / 15m / 1h / 1D
    (docs/05 §7). Pure `analytical_core.indicators.golden_cross` per timeframe;
    computed on read, not persisted, not scored. Returns ``None`` on unknown id."""
    from analytical_core.enums import Timeframe
    from analytical_core.params import effective_params

    inst = get_instrument(db, instrument_id)
    if inst is None:
        return None

    p = effective_params("golden_cross")
    near_pct = float(read_settings(db).get("golden_cross.near_ma_pct", 0.003))

    def _load(tf: Timeframe) -> list[_GBar]:
        rows = db.execute(
            select(
                m.OhlcvBar.ts,
                m.OhlcvBar.open,
                m.OhlcvBar.high,
                m.OhlcvBar.low,
                m.OhlcvBar.close,
                m.OhlcvBar.volume,
                m.OhlcvBar.is_final,
            )
            .where(
                m.OhlcvBar.instrument_id == instrument_id,
                m.OhlcvBar.timeframe == tf,
            )
            .order_by(m.OhlcvBar.ts.desc())
            .limit(_GC_GRID_LOAD)
        ).all()
        return [
            _GBar(
                ts=r.ts,
                open=float(r.open),
                high=float(r.high),
                low=float(r.low),
                close=float(r.close),
                volume=int(r.volume),
                is_final=bool(r.is_final),
            )
            for r in reversed(rows)
        ]

    columns = [
        _gc_grid_column(tf, _load(Timeframe(tf)), inst.instrument_type, near_pct)
        for tf in _GC_GRID_TIMEFRAMES
    ]
    return {
        "instrument_id": instrument_id,
        "contract_key": inst.contract_key,
        "instrument_type": inst.instrument_type.value,
        "generated_at": datetime.now(tz=_utc()).isoformat(),
        "fast_period": int(p["fast_period"]),
        "slow_period": int(p["slow_period"]),
        "ma_type": str(p["ma_type"]),
        "near_ma_pct": near_pct,
        "columns": columns,
        "golden_cross_grid_version": _GC_GRID_VERSION,
    }


# ======================================================================================
# ICT swing Fair Value Gaps — one row per timeframe (docs/07 §4.21, docs/05 §9c)
# ======================================================================================
#
# The 'left-side' FVGs that form into a swing high / low and then act as
# inversion arrays. 5m / 15m / 30m / 1h columns (M30 folded from M5 on read),
# each showing the nearest active gap to price, its CE, and its test / inversion
# state. The pure scan is `analytical_core.fvg.scan_swing_fvgs`. Computed on
# read, not persisted, not scored. Descriptive — no BUY/SELL, no target/stop.

_FVG_GRID_TIMEFRAMES = ("M5", "M15", "M30", "H1")
_FVG_GRID_LOAD = 220  # scan_bars (90) + swing lookback + headroom


def _fvg_dc(f) -> dict | None:
    if f is None:
        return None
    return {
        "kind": f.kind,
        "inversion_kind": f.inversion_kind,
        "swing": f.swing,
        "top": f.top,
        "bottom": f.bottom,
        "ce": f.ce,
        "formed_ts": f.formed_ts,
        "swing_ts": f.swing_ts,
        "bars_since_swing": f.bars_since_swing,
        "state": f.state,
        "reached_ce": f.reached_ce,
        "wick_violated": f.wick_violated,
        "body_respected": f.body_respected,
        "distance_pct": f.distance_pct,
    }


def _fvg_grid_column(tf: str, bars: list) -> dict:
    from analytical_core.fvg import scan_swing_fvgs

    col: dict[str, Any] = {
        "timeframe": tf,
        "status": "INSUFFICIENT_DATA",
        "as_of_ts": None,
        "reason": None,
        "last_price": None,
        "bias": "NEUTRAL",
        "n_active": 0,
        "nearest_above": None,
        "nearest_below": None,
        "fvgs": [],
    }
    if len(bars) < 15:
        col["reason"] = "no bars ingested for this timeframe"
        return col
    scan = scan_swing_fvgs(
        [float(b.high) for b in bars],
        [float(b.low) for b in bars],
        [float(b.close) for b in bars],
        ts=[b.ts.astimezone(_utc()).isoformat() for b in bars],
    )
    col["status"] = "OK"
    col["as_of_ts"] = bars[-1].ts.astimezone(_utc()).isoformat()
    col["last_price"] = scan.last_price
    col["bias"] = scan.bias
    col["n_active"] = sum(1 for f in scan.fvgs if f.state != "BREACHED")
    col["nearest_above"] = _fvg_dc(scan.nearest_above)
    col["nearest_below"] = _fvg_dc(scan.nearest_below)
    col["fvgs"] = [_fvg_dc(f) for f in scan.fvgs]
    return col


def fvg_grid(db: Session, instrument_id: int):
    """ICT swing Fair Value Gaps for 5m / 15m / 30m / 1h (docs/05 §9c). Pure
    scan in ``analytical_core.fvg``; computed on read, not persisted, not scored.
    INDEX + FUTURE only. Returns ``None`` on an unknown id."""
    from analytical_core.enums import InstrumentType, Timeframe
    from analytical_core.fvg import FVG_VERSION

    inst = get_instrument(db, instrument_id)
    if inst is None:
        return None
    applicable = inst.instrument_type in (InstrumentType.INDEX, InstrumentType.FUTURE)

    def _load(tf: Timeframe) -> list[_GBar]:
        rows = db.execute(
            select(
                m.OhlcvBar.ts,
                m.OhlcvBar.open,
                m.OhlcvBar.high,
                m.OhlcvBar.low,
                m.OhlcvBar.close,
                m.OhlcvBar.volume,
                m.OhlcvBar.is_final,
            )
            .where(
                m.OhlcvBar.instrument_id == instrument_id,
                m.OhlcvBar.timeframe == tf,
            )
            .order_by(m.OhlcvBar.ts.desc())
            .limit(_FVG_GRID_LOAD)
        ).all()
        return [
            _GBar(
                ts=r.ts,
                open=float(r.open),
                high=float(r.high),
                low=float(r.low),
                close=float(r.close),
                volume=int(r.volume),
                is_final=bool(r.is_final),
            )
            for r in reversed(rows)
        ]

    m5 = _load(Timeframe.M5) if applicable else []
    columns: list[dict] = []
    for tf in _FVG_GRID_TIMEFRAMES:
        if not applicable:
            columns.append(
                {
                    **_fvg_grid_column(tf, []),
                    "status": "NOT_APPLICABLE",
                    "reason": "swing FVGs run on INDEX / FUTURE only (docs/04 §4)",
                }
            )
            continue
        bars = m5 if tf == "M5" else _fold_m5_to_m30(m5) if tf == "M30" else _load(Timeframe(tf))
        columns.append(_fvg_grid_column(tf, bars))

    return {
        "instrument_id": instrument_id,
        "contract_key": inst.contract_key,
        "instrument_type": inst.instrument_type.value,
        "generated_at": datetime.now(tz=_utc()).isoformat(),
        "columns": columns,
        "fvg_grid_version": FVG_VERSION,
    }


# ======================================================================================
# CPR + classic pivots — daily / weekly / monthly (docs/07 §4.18, docs/05 §10.13)
# ======================================================================================
#
# Forward-looking support / resistance drawn from the last completed period's
# H/L/C: the CPR band (TC / pivot / BC) and classic floor R1-R3 / S1-S3, for the
# daily, weekly and monthly periods, with ~3 months of history and the levels
# for the developing (in-progress) period too. Computed on read from D1 bars —
# not persisted, not scored. Descriptive: no bias, no BUY/SELL, no target/stop.

_PIVOTS_VERSION = "0.1.0"
_PIVOT_TFS = ("DAILY", "WEEKLY", "MONTHLY")


def _pivot_level_rows(pl, last_price: float, at: float, near: float, timeframe: str) -> list[dict]:
    rows = []
    for name, price in pl.levels():
        dist = price - last_price
        a = abs(dist)
        tier = "AT" if a <= at else "NEAR" if a <= near else "FAR"
        side = "AT" if a <= at else ("ABOVE" if dist > 0 else "BELOW")
        rows.append(
            {
                "timeframe": timeframe,
                "name": name,
                "price": round(price, 2),
                "distance": round(dist, 2),
                "distance_pct": round(dist / last_price * 100.0, 3) if last_price else None,
                "tier": tier,
                "side": side,
            }
        )
    return rows


def pivots_view(
    db: Session,
    instrument_id: int,
    *,
    daily_history: int = 66,
    weekly_history: int = 13,
    monthly_history: int = 4,
    daily_on: str | None = None,
    daily_years: int = 20,
):
    """CPR + classic pivots for the daily / weekly / monthly periods (docs/05
    §10.13). Pure math in ``analytical_core.pivots``; this only fetches D1 bars
    and folds them into weeks / months. Returns ``None`` if the id is unknown.

    ``daily_on`` = ``"MM-DD"`` switches the **daily** history to a same-calendar-
    date view: the pivots for the first session on/after that date in each of the
    last ``daily_years`` years, with that session's realised move."""
    import datetime as _dtmod

    from analytical_core.pivots import compute_pivots, cpr_relation, width_band
    from app.ingestion.session import IST

    inst = get_instrument(db, instrument_id)
    if inst is None:
        return None

    md: tuple[int, int] | None = None
    if daily_on:
        try:
            mm, dd = (int(x) for x in daily_on.split("-"))
            _dtmod.date(2000, mm, dd)  # validate (2000 is a leap year → 02-29 ok)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"daily_on must be 'MM-DD', got {daily_on!r}") from exc
        md = (mm, dd)

    at, near, _appr = _default_key_bands(inst.contract_key)
    load = max(daily_history + 8, 7 * (weekly_history + 3), 31 * (monthly_history + 2)) + 20
    if md is not None:
        load = max(load, daily_years * 320 + 40)  # ~20y of trading days for the calendar view
    raw = db.execute(
        select(
            m.OhlcvBar.ts,
            m.OhlcvBar.open,
            m.OhlcvBar.high,
            m.OhlcvBar.low,
            m.OhlcvBar.close,
            m.OhlcvBar.is_final,
        )
        .where(
            m.OhlcvBar.instrument_id == instrument_id,
            m.OhlcvBar.timeframe == Timeframe.D1,
        )
        .order_by(m.OhlcvBar.ts.desc())
        .limit(load)
    ).all()
    d1 = list(reversed(raw))  # ascending by ts

    now = datetime.now(tz=_utc())
    today_ist = now.astimezone(IST).date()

    # latest price — last M5 close within 4 days, else the last D1 close
    m5 = db.execute(
        select(m.OhlcvBar.close, m.OhlcvBar.ts)
        .where(
            m.OhlcvBar.instrument_id == instrument_id,
            m.OhlcvBar.timeframe == Timeframe.M5,
            m.OhlcvBar.ts >= now - timedelta(days=4),
        )
        .order_by(m.OhlcvBar.ts.desc())
        .limit(1)
    ).first()
    if m5:
        last_price, last_price_ts = float(m5[0]), m5[1]
    elif d1:
        last_price, last_price_ts = float(d1[-1].close), d1[-1].ts
    else:
        last_price, last_price_ts = None, None

    def _ist_date(ts):
        return ts.astimezone(IST).date()

    def _fold(key_fn):
        """[(key, {start,end,high,low,close,n,last_final})] ascending by key."""
        acc: dict = {}
        for b in d1:
            dte = _ist_date(b.ts)
            k = key_fn(dte)
            hi, lo, cl = float(b.high), float(b.low), float(b.close)
            e = acc.get(k)
            if e is None:
                acc[k] = {
                    "start": dte,
                    "end": dte,
                    "high": hi,
                    "low": lo,
                    "close": cl,
                    "n": 1,
                    "last_final": bool(b.is_final),
                }
            else:
                e["high"] = max(e["high"], hi)
                e["low"] = min(e["low"], lo)
                e["close"] = cl  # bars ascending → last close of the period
                e["end"] = dte
                e["n"] += 1
                e["last_final"] = bool(b.is_final)
        return sorted(acc.items())

    key_fns = {
        "DAILY": lambda dte: dte,
        "WEEKLY": lambda dte: dte.isocalendar()[:2],
        "MONTHLY": lambda dte: (dte.year, dte.month),
    }
    cur_key = {
        "DAILY": today_ist,
        "WEEKLY": today_ist.isocalendar()[:2],
        "MONTHLY": (today_ist.year, today_ist.month),
    }
    history_n = {"DAILY": daily_history, "WEEKLY": weekly_history, "MONTHLY": monthly_history}

    def _next_label(tf: str, last_end) -> tuple[str, str | None]:
        """(human label, resolved ISO date) for the period a `next` set applies to."""
        if tf == "DAILY":
            row = next_trading_day_row(db, last_end + timedelta(days=1))
            if row is not None:
                return (
                    f"next session ({row.calendar_date.isoformat()})",
                    row.calendar_date.isoformat(),
                )
            nxt = (last_end + timedelta(days=1)).isoformat()
            return f"next session (~{nxt})", nxt
        if tf == "WEEKLY":
            return "next week", None
        return "next month", None

    def _period_out(key, p, *, prev_p=None):
        pl = compute_pivots(p["high"], p["low"], p["close"])
        out = {
            "from_period": {
                "start": p["start"].isoformat(),
                "end": p["end"].isoformat(),
                "sessions": p["n"],
                "high": round(p["high"], 2),
                "low": round(p["low"], 2),
                "close": round(p["close"], 2),
            },
            "pivot": round(pl.pivot, 2),
            "tc": round(pl.tc, 2),  # by formula (2·P − BC); can fall below bc on a weak close
            "bc": round(pl.bc, 2),  # (high + low) / 2
            "cpr_top": round(pl.cpr_top, 2),  # max(tc, bc) — the band's upper line
            "cpr_bottom": round(pl.cpr_bottom, 2),  # min(tc, bc)
            "cpr_width": round(pl.cpr_width, 2),
            "cpr_width_pct": round(pl.cpr_width_pct, 3),
            "width_band": width_band(pl.cpr_width_pct).value,
            "r1": round(pl.r1, 2),
            "r2": round(pl.r2, 2),
            "r3": round(pl.r3, 2),
            "s1": round(pl.s1, 2),
            "s2": round(pl.s2, 2),
            "s3": round(pl.s3, 2),
            "vs_prev": (
                cpr_relation(
                    pl, compute_pivots(prev_p["high"], prev_p["low"], prev_p["close"])
                ).value
                if prev_p
                else None
            ),
        }
        return pl, out

    timeframes: dict = {}
    all_current_rows: list[dict] = []
    for tf in _PIVOT_TFS:
        folded = _fold(key_fns[tf])
        block: dict = {"current": None, "next": None, "history": []}
        if folded:
            last_k, last_p = folded[-1]
            # is the most recent period still in progress?
            in_progress = last_k >= cur_key[tf] and not (tf == "DAILY" and last_p["last_final"])
            completed = folded[:-1] if in_progress else folded
            # current = the period whose pivots are in force now:
            #   mid-period → the last completed period (completed[-1]);
            #   period done → the one before it (completed[-2]).
            cur_idx = len(completed) - 1 if in_progress else len(completed) - 2
            if cur_idx >= 0:
                ck, cp = completed[cur_idx]
                cprev = completed[cur_idx - 1][1] if cur_idx >= 1 else None
                pl, cur = _period_out(ck, cp, prev_p=cprev)
                block["current"] = cur
                all_current_rows += (
                    _pivot_level_rows(pl, last_price, at, near, tf) if last_price else []
                )
            # next = pivots for the upcoming period, from the most recent period's H/L/C
            nprev = folded[-2][1] if len(folded) >= 2 else None
            _, nxt = _period_out(last_k, last_p, prev_p=nprev)
            label, for_date = _next_label(tf, last_p["end"])
            nxt["for_label"] = label
            nxt["for_date"] = for_date
            nxt["provisional"] = in_progress  # numbers still move until the period closes
            block["next"] = nxt
            # history = completed periods, newest first
            hist = []
            for i in range(len(completed) - 1, -1, -1):
                if len(hist) >= history_n[tf]:
                    break
                _, row = _period_out(
                    completed[i][0],
                    completed[i][1],
                    prev_p=completed[i - 1][1] if i >= 1 else None,
                )
                hist.append(row)
            block["history"] = hist
        timeframes[tf] = block

    daily_history_mode = "RECENT"
    if md is not None and d1:
        mm, dd = md
        dates = [_ist_date(b.ts) for b in d1]

        def _target(year: int):
            try:
                return _dtmod.date(year, mm, dd)
            except ValueError:  # e.g. Feb 29 in a common year → 1st of the next month
                return _dtmod.date(year + (mm == 12), (mm % 12) + 1, 1)

        by_year: dict[int, int] = {}  # year -> first d1 index on/after the target date
        for i, dte in enumerate(dates):
            tgt = _target(dte.year)
            if dte >= tgt and (dte - tgt).days <= 7 and dte.year not in by_year:
                by_year[dte.year] = i
        rows = []
        prev_pl = None
        for yr in sorted(by_year):  # ascending → vs_prev compares to the earlier year
            i = by_year[yr]
            t, prior = d1[i], (d1[i - 1] if i > 0 else None)
            if prior is None:
                continue
            pl, row = _period_out(
                dates[i - 1],
                {
                    "start": dates[i - 1],
                    "end": dates[i - 1],
                    "high": float(prior.high),
                    "low": float(prior.low),
                    "close": float(prior.close),
                    "n": 1,
                    "last_final": True,
                },
            )
            row["year"] = yr
            row["for_date"] = dates[i].isoformat()
            row["vs_prev"] = cpr_relation(pl, prev_pl).value if prev_pl else None
            o, h, low_, c = float(t.open), float(t.high), float(t.low), float(t.close)
            pc = float(prior.close)
            row["realized"] = {
                "open": round(o, 2),
                "high": round(h, 2),
                "low": round(low_, 2),
                "close": round(c, 2),
                "prev_close": round(pc, 2),
                "ret_pct": round((c - pc) / pc * 100.0, 3) if pc else None,
                "range_pct": round((h - low_) / pc * 100.0, 3) if pc else None,
                "close_vs_pivot": (
                    "ABOVE" if c > pl.pivot + at else "BELOW" if c < pl.pivot - at else "AT"
                ),
                "touched_r1": h >= pl.r1,
                "touched_s1": low_ <= pl.s1,
            }
            rows.append(row)
            prev_pl = pl
        rows = rows[::-1][:daily_years]  # newest year first
        timeframes["DAILY"]["history"] = rows
        daily_history_mode = "CALENDAR_DATE"

    near_above = min(
        (r for r in all_current_rows if r["side"] == "ABOVE"),
        key=lambda r: r["distance"],
        default=None,
    )
    near_below = max(
        (r for r in all_current_rows if r["side"] == "BELOW"),
        key=lambda r: r["distance"],
        default=None,
    )
    alerts = sorted(
        (r for r in all_current_rows if r["tier"] != "FAR"),
        key=lambda r: abs(r["distance"]),
    )

    return {
        "instrument_id": instrument_id,
        "contract_key": inst.contract_key,
        "instrument_type": inst.instrument_type.value,
        "generated_at": now.isoformat(),
        "last_price": round(last_price, 2) if last_price is not None else None,
        "last_price_ts": last_price_ts.isoformat() if last_price_ts is not None else None,
        "bands": {"at": at, "near": near},
        "d1_bars_used": len(d1),
        "daily_history_mode": daily_history_mode,  # RECENT | CALENDAR_DATE
        "daily_on": (f"{md[0]:02d}-{md[1]:02d}" if md else None),
        "timeframes": timeframes,
        "nearest_above": near_above,
        "nearest_below": near_below,
        "alerts": alerts,
        "pivots_version": _PIVOTS_VERSION,
    }


# ======================================================================================
# Opening-range breakout backtest (docs/16, docs/07 §4.15)
# ======================================================================================


def _hm_to_min(s: str) -> int:
    try:
        h, m = s.split(":")
        v = int(h) * 60 + int(m)
    except ValueError as exc:
        raise ValueError(f"time must be 'HH:MM', got {s!r}") from exc
    if not 0 <= v < 1440:
        raise ValueError(f"time out of range: {s!r}")
    return v


def orb_backtest(
    db: Session,
    index_id: int,
    *,
    start,
    end,
    range_start: str,
    range_end: str,
    break_start: str,
    break_end: str,
    measure_until: str | None = None,
    targets: str = "0.5,1.0",
    timeframe: str = "M1",
):
    """Opening-range breakout backtest for an INDEX over ``[start, end]`` IST
    dates (docs/16). Loads M1/M15 bars, groups by IST session date, hands them
    to the pure ``analytical_core.backtest.run_orb``. Not persisted. ``None`` if
    the id is not an INDEX. Raises ``ValueError`` on bad times / range."""
    from datetime import datetime, time

    from analytical_core.backtest import Bar, DayBars, OrbConfig, run_orb
    from analytical_core.versioning import ALGO_VERSION
    from app.ingestion.session import IST

    inst = get_instrument(db, index_id)
    if inst is None or inst.instrument_type is not InstrumentType.INDEX:
        return None
    if (end - start).days < 0:
        raise ValueError("end must be on or after start")
    if (end - start).days > 1100:
        raise ValueError("date range too wide (max ~3 years)")

    tf = Timeframe.M15 if timeframe.upper() == "M15" else Timeframe.M1
    mults = tuple(float(x) for x in targets.split(",") if x.strip())
    cfg = OrbConfig(
        range_start=_hm_to_min(range_start),
        range_end=_hm_to_min(range_end),
        break_start=_hm_to_min(break_start),
        break_end=_hm_to_min(break_end),
        measure_until=_hm_to_min(measure_until) if measure_until else _hm_to_min(break_end),
        target_mults=mults or (0.5, 1.0),
    )
    cfg.validate()

    start_utc = datetime.combine(start, time.min, IST).astimezone(_utc())
    end_utc = datetime.combine(end, time.max, IST).astimezone(_utc())

    by_date: dict[str, list[Bar]] = {}
    for ts, o, h, low, c in db.execute(
        select(m.OhlcvBar.ts, m.OhlcvBar.open, m.OhlcvBar.high, m.OhlcvBar.low, m.OhlcvBar.close)
        .where(
            m.OhlcvBar.instrument_id == index_id,
            m.OhlcvBar.timeframe == tf,
            m.OhlcvBar.ts >= start_utc,
            m.OhlcvBar.ts <= end_utc,
        )
        .order_by(m.OhlcvBar.ts)
    ):
        ist = ts.astimezone(IST)
        by_date.setdefault(ist.date().isoformat(), []).append(
            Bar(
                minute=ist.hour * 60 + ist.minute,
                open=float(o),
                high=float(h),
                low=float(low),
                close=float(c),
            )
        )

    days = [
        DayBars(
            date=d,
            weekday=datetime.fromisoformat(d).weekday(),
            bars=tuple(sorted(bars, key=lambda b: b.minute)),
        )
        for d, bars in sorted(by_date.items())
    ]
    res = run_orb(days, cfg)
    return {
        "index_id": index_id,
        "underlying_symbol": inst.symbol,
        "timeframe": tf.value,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "algo_version": ALGO_VERSION,
        **_dc_asdict(res),
    }


def _dc_asdict(obj) -> dict:
    from dataclasses import asdict

    return asdict(obj)


# ======================================================================================
# config + calendar (docs/07 §4.7, §4.8)
# ======================================================================================


def read_settings(db: Session) -> dict:
    from app.settings_store import load_app_settings

    return load_app_settings(db)


def upsert_settings(db: Session, values: dict) -> None:
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    for k, v in values.items():
        stmt = pg_insert(m.AppSetting).values(key=k, value=v)
        stmt = stmt.on_conflict_do_update(index_elements=["key"], set_={"value": v})
        db.execute(stmt)
    db.commit()


def calendar_rows(db: Session, start, end, *, exchange="NSE", segment="FO"):
    return list(
        db.execute(
            select(m.MarketCalendar)
            .where(
                m.MarketCalendar.exchange == exchange,
                m.MarketCalendar.segment == segment,
                m.MarketCalendar.calendar_date >= start,
                m.MarketCalendar.calendar_date <= end,
            )
            .order_by(m.MarketCalendar.calendar_date)
        ).scalars()
    )


def calendar_row_for(db: Session, on, *, exchange="NSE", segment="FO"):
    return db.execute(
        select(m.MarketCalendar).where(
            m.MarketCalendar.exchange == exchange,
            m.MarketCalendar.segment == segment,
            m.MarketCalendar.calendar_date == on,
        )
    ).scalar_one_or_none()


def next_trading_day_row(db: Session, after, *, exchange="NSE", segment="FO"):
    return db.execute(
        select(m.MarketCalendar)
        .where(
            m.MarketCalendar.exchange == exchange,
            m.MarketCalendar.segment == segment,
            m.MarketCalendar.calendar_date >= after,
            m.MarketCalendar.is_trading_day.is_(True),
        )
        .order_by(m.MarketCalendar.calendar_date)
        .limit(1)
    ).scalar_one_or_none()


def calendar_seeded_until(db: Session, *, exchange="NSE", segment="FO"):
    return db.execute(
        select(func.max(m.MarketCalendar.calendar_date)).where(
            m.MarketCalendar.exchange == exchange, m.MarketCalendar.segment == segment
        )
    ).scalar()


def latest_run(db: Session):
    return db.execute(
        select(m.AnalysisRun).order_by(m.AnalysisRun.cycle_seq.desc()).limit(1)
    ).scalar_one_or_none()


def last_successful_run(db: Session):
    from analytical_core.enums import RunStatus

    return db.execute(
        select(m.AnalysisRun)
        .where(m.AnalysisRun.status.in_((RunStatus.SUCCEEDED, RunStatus.PARTIAL)))
        .order_by(m.AnalysisRun.cycle_seq.desc())
        .limit(1)
    ).scalar_one_or_none()
