"""analytical_core — pure analysis + scoring engine.

Contents: the authoritative enum contract (``enums``), versioning constants
(``versioning``), parameter provenance helpers (``params``), the result/score
envelopes (``results``), the deterministic indicators (``indicators``), Market
Profile (``market_profile``), and the scoring aggregation (``scoring``).

Hard rule (docs/CLAUDE.md §7.3): this package imports nothing from ``app`` and
performs no IO. Standard library + numpy only.

Import submodules explicitly, e.g. ``from analytical_core import enums``.
"""

__all__ = ["enums", "params", "versioning", "results", "scoring"]
