"""Pydantic wire models for the API (docs/07 §5).

Enum-typed fields import their enum from ``analytical_core.enums`` so the
OpenAPI schema and the generated TypeScript client stay bound to the one
authoritative contract (docs/12).
"""
