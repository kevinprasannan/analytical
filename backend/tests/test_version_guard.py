"""Version guard (docs/09 §2.1).

A committed digest of the deterministic engine surface. Any change to a formula,
default parameter, rounding, tie-break, or approximation shifts the digest; the
fix is to regenerate the fixture **and** bump ``ALGO_VERSION`` /
``SCORING_VERSION`` in the same commit::

    python -m tests.support.engine_snapshot
"""

from __future__ import annotations

import hashlib
import json
import re

from analytical_core.versioning import ALGO_VERSION, SCORING_VERSION
from tests.support.engine_snapshot import FIXTURE, build_snapshot, snapshot_payload

_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def test_versions_are_semver():
    assert _SEMVER.match(ALGO_VERSION), ALGO_VERSION
    assert _SEMVER.match(SCORING_VERSION), SCORING_VERSION


def test_fixture_records_the_current_versions():
    stored = json.loads(FIXTURE.read_text())
    assert (
        stored["algo_version"] == ALGO_VERSION
    ), "engine_snapshot.json is for a different ALGO_VERSION — regenerate it"
    assert (
        stored["scoring_version"] == SCORING_VERSION
    ), "engine_snapshot.json is for a different SCORING_VERSION — regenerate it"


def test_engine_output_matches_the_committed_snapshot():
    current = snapshot_payload()
    stored = json.dumps(json.loads(FIXTURE.read_text()), sort_keys=True, separators=(",", ":"))
    assert _digest(current) == _digest(stored), (
        "deterministic engine output changed.\n"
        "If this was intentional: run `python -m tests.support.engine_snapshot` and bump "
        "ALGO_VERSION (and/or SCORING_VERSION) in the same commit.\n"
        "If not: you changed a formula / default / rounding / tie-break by accident."
    )


def test_snapshot_is_deterministic():
    assert build_snapshot() == build_snapshot()
