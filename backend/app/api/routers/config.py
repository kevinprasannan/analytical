"""Configuration (docs/07 §4.7). Edits land in ``app_settings`` and apply from
the next cycle."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api import config_model as cm
from app.api import services
from app.api.deps import Principal, get_current_principal, get_db
from app.api.errors import ApiError

router = APIRouter(prefix="/api/v1/config", tags=["config"])


@router.get("")
def get_config(db: Session = Depends(get_db)) -> dict[str, Any]:
    flat = cm.effective(services.read_settings(db))
    return {
        "effective": flat,
        "sections": cm.sectioned(flat),
        "config_params_hash": cm.config_params_hash(flat),
    }


@router.patch("")
def patch_config(
    body: dict[str, Any],
    db: Session = Depends(get_db),
    _principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    try:
        clean = cm.validate_patch(body)
    except cm.ConfigError as exc:
        raise ApiError(422, "Unprocessable Entity", str(exc)) from None
    services.upsert_settings(db, clean)
    flat = cm.effective(services.read_settings(db))
    return {
        "updated": sorted(clean),
        "effective_from": "the next cycle",
        "config_params_hash": cm.config_params_hash(flat),
    }


@router.get("/schema")
def config_schema() -> dict[str, Any]:
    return cm.json_schema()
