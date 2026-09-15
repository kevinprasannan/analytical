"""Market board (docs/07 §4.11).

``GET /board`` — one compact row per tracked INDEX / FUTURE: latest price,
today's move, range, open interest and the D1/H1 label. Pure DB read; the
dashboard's landing view. Options are not here (they belong to the option chain).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api import services
from app.api.deps import get_db
from app.api.schemas.board import BoardRow, MarketBoard

router = APIRouter(prefix="/api/v1", tags=["board"])


@router.get("/board", response_model=MarketBoard)
def board(db: Session = Depends(get_db)) -> MarketBoard:
    return MarketBoard(rows=[BoardRow(**r) for r in services.market_board(db)])
