"""Instruments + coverage (docs/07 §4.2, §4.3)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi import status as http_status
from sqlalchemy.orm import Session

from analytical_core.enums import InstrumentType, Timeframe
from app.api import services
from app.api.deps import Principal, get_current_principal, get_db
from app.api.errors import not_found
from app.api.schemas.common import Page
from app.api.schemas.instruments import (
    CatalogItem,
    InstrumentCatalog,
    InstrumentCoverage,
    InstrumentCreate,
    InstrumentCreated,
    InstrumentDeleted,
    InstrumentDetail,
    InstrumentPatch,
    InstrumentSummary,
    ProviderMapSummary,
)
from app.api.schemas.marketdata import Bar, BarsResponse, OiPoint, OpenInterestResponse
from app.config import get_settings

router = APIRouter(prefix="/api/v1/instruments", tags=["instruments"])


def _summary(inst) -> InstrumentSummary:
    return InstrumentSummary.model_validate(inst, from_attributes=True)


@router.get("", response_model=Page[InstrumentSummary])
def list_instruments(
    db: Session = Depends(get_db),
    instrument_type: InstrumentType | None = None,
    segment: str | None = None,
    underlying_id: int | None = None,
    is_tracked: bool | None = None,
    option_type: str | None = None,
    q: str | None = None,
    sort: str = "symbol",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Page[InstrumentSummary]:
    rows, total = services.list_instruments(
        db,
        instrument_type=instrument_type,
        segment=segment,
        underlying_id=underlying_id,
        is_tracked=is_tracked,
        option_type=option_type,
        q=q,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return Page(items=[_summary(r) for r in rows], total=total, limit=limit, offset=offset)


@router.get("/catalog", response_model=InstrumentCatalog)
def instrument_catalog(
    q: str = Query(..., min_length=2, description="substring of the Upstox key / name / symbol"),
    instrument_type: str | None = Query(None, description="INDEX | FUTURE | OPTION"),
    exchange: str | None = Query(None, description="NSE | BSE"),
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
) -> InstrumentCatalog:
    from sqlalchemy import select as _select

    from app.db import models as md
    from app.providers.upstox import catalog

    s = get_settings()
    rows = catalog.search_master(
        s.upstox_master_dir, q, instrument_type=instrument_type, exchange=exchange, limit=limit
    )
    from pathlib import Path as _P

    available = _P(s.upstox_master_dir).is_dir() and any(_P(s.upstox_master_dir).glob("*.json*"))
    known = {
        k
        for (k,) in db.execute(
            _select(md.ProviderInstrumentMap.provider_symbol).where(
                md.ProviderInstrumentMap.provider == s.active_provider
            )
        )
    }
    items = [
        CatalogItem(
            **{f: getattr(r, f) for f in CatalogItem.model_fields if f != "in_db"},
            in_db=r.provider_symbol in known,
        )
        for r in rows
    ]
    return InstrumentCatalog(query=q, count=len(items), available=bool(available), items=items)


@router.get("/{instrument_id}", response_model=InstrumentDetail)
def get_instrument(instrument_id: int, db: Session = Depends(get_db)) -> InstrumentDetail:
    inst = services.get_instrument(db, instrument_id)
    if inst is None:
        raise not_found("instrument")
    detail = InstrumentDetail.model_validate(inst, from_attributes=True)
    detail.provider_map = [
        ProviderMapSummary(
            provider=p.provider, provider_symbol=p.provider_symbol, is_active=p.is_active
        )
        for p in services.provider_map_for(db, instrument_id)
    ]
    detail.applicable_analyses = services.applicable_analyses(inst)
    return detail


@router.post("", response_model=InstrumentCreated, status_code=http_status.HTTP_201_CREATED)
def create_instrument(
    body: InstrumentCreate,
    db: Session = Depends(get_db),
    _principal: Principal = Depends(get_current_principal),
) -> InstrumentCreated:
    result = services.create_instrument(db, body.model_dump(mode="json"))
    return InstrumentCreated(**result)


@router.delete("/{instrument_id}", response_model=InstrumentDeleted)
def delete_instrument(
    instrument_id: int,
    force: bool = Query(False, description="also delete instruments that use this as underlying"),
    db: Session = Depends(get_db),
    _principal: Principal = Depends(get_current_principal),
) -> InstrumentDeleted:
    result = services.delete_instrument(db, instrument_id, force=force)
    if result is None:
        raise not_found("instrument")
    return InstrumentDeleted(**result)


@router.patch("/{instrument_id}", response_model=InstrumentDetail)
def patch_instrument(
    instrument_id: int,
    patch: InstrumentPatch,
    db: Session = Depends(get_db),
    _principal: Principal = Depends(get_current_principal),
) -> InstrumentDetail:
    inst = services.get_instrument(db, instrument_id)
    if inst is None:
        raise not_found("instrument")
    if patch.is_tracked is not None:
        inst.is_tracked = patch.is_tracked
    if patch.profile_bin_size is not None:
        inst.profile_bin_size = patch.profile_bin_size
    db.commit()
    db.refresh(inst)
    return get_instrument(instrument_id, db)


@router.get("/{instrument_id}/coverage", response_model=InstrumentCoverage)
def coverage(instrument_id: int, db: Session = Depends(get_db)) -> InstrumentCoverage:
    if services.get_instrument(db, instrument_id) is None:
        raise not_found("instrument")
    return services.coverage(db, instrument_id, get_settings().active_provider)


@router.get("/{instrument_id}/bars", response_model=BarsResponse)
def bars(
    instrument_id: int,
    timeframe: Timeframe,
    db: Session = Depends(get_db),
    start: datetime | None = None,
    end: datetime | None = None,
    include_forming: bool = False,
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
) -> BarsResponse:
    if services.get_instrument(db, instrument_id) is None:
        raise not_found("instrument")
    rows, total = services.list_bars(
        db,
        instrument_id,
        timeframe=timeframe,
        provider=get_settings().active_provider,
        start=start,
        end=end,
        limit=limit,
        offset=offset,
        include_forming=include_forming,
    )
    return BarsResponse(
        instrument_id=instrument_id,
        timeframe=timeframe,
        items=[Bar.model_validate(r, from_attributes=True) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{instrument_id}/open-interest", response_model=OpenInterestResponse)
def open_interest(
    instrument_id: int,
    db: Session = Depends(get_db),
    timeframe: Timeframe = Timeframe.M1,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
) -> OpenInterestResponse:
    inst = services.get_instrument(db, instrument_id)
    if inst is None:
        raise not_found("instrument")
    if inst.instrument_type is InstrumentType.INDEX:
        from analytical_core.enums import AnalysisStatus

        return OpenInterestResponse(
            instrument_id=instrument_id,
            timeframe=timeframe,
            status=AnalysisStatus.NOT_APPLICABLE,
            reason="index instruments have no open interest",
        )
    rows, total = services.list_oi(
        db,
        instrument_id,
        timeframe=timeframe,
        provider=get_settings().active_provider,
        start=start,
        end=end,
        limit=limit,
        offset=offset,
    )
    return OpenInterestResponse(
        instrument_id=instrument_id,
        timeframe=timeframe,
        items=[OiPoint.model_validate(r, from_attributes=True) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
