"""Shared response envelopes (docs/07 §3)."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int
    next_cursor: str | None = None


class Problem(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str
    instance: str | None = None
    errors: dict[str, str] | None = None


class Provenance(BaseModel):
    algo_version: str
    params_id: str
    params_hash: str
    input_window_start: str | None = None
    input_window_end: str | None = None
    bars_used: int | None = None
    coverage_ratio: float | None = None
    warmup_ok: bool | None = None
    last_bar_final: bool | None = None
    provisional: bool = False


class PageParams(BaseModel):
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
