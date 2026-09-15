"""Index constituents / weightage (docs/07 §4.14, docs/15).

``GET /instruments/{index_id}/constituents`` — the names that make up an index,
**ordered by weight**, with running cumulative weight, sector rollup,
concentration, and (when a quote is reachable per name) each name's day
contribution to the index move + market breadth. ``?include_beta=true`` adds
rolling beta / correlation vs the index (a heavier read — one D1 history fetch
per name). Weights are seeded reference data (`analytical-index-weights load`);
the analytics are pure `analytical_core.indices`. Descriptive — no signal.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api import services
from app.api.deps import get_db
from app.api.errors import ApiError, not_found
from app.api.schemas.index_constituents import IndexConstituentsResponse
from app.providers.base import ProviderAuthError, ProviderError

router = APIRouter(prefix="/api/v1", tags=["index-constituents"])


@router.get("/instruments/{index_id}/constituents", response_model=IndexConstituentsResponse)
def index_constituents(
    index_id: int,
    effective_date: date | None = Query(
        None, description="weights as of this rebalance date (default: latest loaded)"
    ),
    include_beta: bool = Query(
        False, description="also compute rolling beta / correlation vs the index"
    ),
    lookback: int = Query(60, ge=5, le=500, description="D1 sessions for beta / correlation"),
    as_of_date: date | None = Query(
        None,
        description=(
            "replay this past session instead of a live quote: each name's D1 close "
            "vs. its prior close, on or before this date (past-data analysis)"
        ),
    ),
    db: Session = Depends(get_db),
) -> IndexConstituentsResponse:
    if services.get_instrument(db, index_id) is None:
        raise not_found("instrument")
    try:
        view = services.index_constituents(
            db,
            index_id,
            effective_date=effective_date,
            include_beta=include_beta,
            lookback=lookback,
            as_of_date=as_of_date,
        )
    except ValueError as exc:
        raise ApiError(422, "Unprocessable Entity", str(exc)) from exc
    except (ProviderError, ProviderAuthError) as exc:
        raise ApiError(502, "Provider Error", f"constituent quote fetch failed: {exc}") from exc
    if view is None:
        raise not_found(
            "index constituents (not an INDEX, or no weights seeded — run "
            "`analytical-index-weights load`)"
        )
    return IndexConstituentsResponse.model_validate(
        {"index_id": index_id, "historical": as_of_date is not None, **asdict(view)}
    )
