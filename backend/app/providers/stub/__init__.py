"""Deterministic, clearly-synthetic provider for Phase-1 tests and local dev.

This fills the docs/09 ``MockProvider`` role. Every value it returns is fictional
and tagged ``source="STUB_FIXTURE"``; it must never be treated as real market
data. It supports exercising success / insufficient-data / unavailable-capability
/ authentication-failure / rate-limit / error paths via ``StubBehavior``.
"""

from app.providers.stub.provider import StubBehavior, StubProvider

__all__ = ["StubBehavior", "StubProvider"]
