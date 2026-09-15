"""Meta endpoints (docs/07 §4.1).

``/meta/enums`` serves the authoritative enum registry (docs/12) so the frontend
has one runtime source. Values come straight from ``analytical_core.enums``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from analytical_core import versioning
from analytical_core.enums import USER_FACING_TIMEFRAMES, emit_json
from app.api import config_model, services
from app.api.deps import get_db
from app.config import get_settings

router = APIRouter(prefix="/api/v1/meta", tags=["meta"])


@router.get("/enums")
def enums() -> dict[str, dict[str, Any]]:
    return emit_json()


@router.get("/timeframes")
def timeframes() -> dict[str, list[str]]:
    return {"user_facing": [tf.value for tf in USER_FACING_TIMEFRAMES]}


#: analysis-applicability matrix (docs/04 §4). OK = normally OK-path,
#: NA = NOT_APPLICABLE by design (no confidence penalty),
#: INSUF = applicable but commonly INSUFFICIENT_DATA for that type.
_APPLICABILITY = {
    "rsi": {"scope": "PER_TIMEFRAME", "INDEX": "OK", "FUTURE": "OK", "OPTION": "OK"},
    "bollinger": {"scope": "PER_TIMEFRAME", "INDEX": "OK", "FUTURE": "OK", "OPTION": "OK"},
    "ema7": {"scope": "PER_TIMEFRAME", "INDEX": "OK", "FUTURE": "OK", "OPTION": "OK"},
    "golden_cross": {"scope": "PER_TIMEFRAME", "INDEX": "OK", "FUTURE": "NA", "OPTION": "NA"},
    "volume": {
        "scope": "PER_TIMEFRAME",
        "INDEX": "OK_IF_HAS_VOLUME",
        "FUTURE": "OK",
        "OPTION": "OK",
    },
    "open_interest": {"scope": "PER_TIMEFRAME", "INDEX": "NA", "FUTURE": "OK", "OPTION": "OK"},
    "market_profile": {"scope": "SESSION", "INDEX": "OK", "FUTURE": "OK", "OPTION": "INSUF"},
}


@router.get("/applicability")
def applicability() -> dict[str, dict[str, str]]:
    return _APPLICABILITY


@router.get("/versions")
def versions(db: Session = Depends(get_db)) -> dict[str, Any]:
    settings = get_settings()
    stale = services.stale_result_counts(db)
    try:
        flat = config_model.effective(services.read_settings(db))
    except SQLAlchemyError:
        db.rollback()
        flat = config_model.effective({})  # overrides unreadable -> defaults
    return {
        "algo_version": versioning.ALGO_VERSION,
        "scoring_version": versioning.SCORING_VERSION,
        "active_provider": settings.active_provider,
        "git_sha": settings.git_sha,
        "config_params_hash": config_model.config_params_hash(flat),
        "stale_results": stale["analysis_results"] > 0 or stale["signal_scores"] > 0,
        "stale_result_counts": stale,
    }
