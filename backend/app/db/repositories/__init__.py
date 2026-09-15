"""Repository seam (docs/02 §3.8).

The worker and services depend on the protocols in ``protocols.py``. Two
implementations ship in Phase 1:

  * ``memory``      — deterministic in-memory repos; used by worker-lifecycle
                      tests and local dev without a database.
  * ``sqlalchemy``  — PostgreSQL-backed repos; used by the ``@pytest.mark.db``
                      tests and real runs.

Both must satisfy the same protocols and produce the same projection contents
from the same inputs (``rebuild_projections``).
"""

from app.db.repositories.protocols import (
    AnalysisResultRepository,
    InstrumentRepository,
    InstrumentView,
    ProjectionRepository,
    Repositories,
    RunRepository,
    ScoreRepository,
)

__all__ = [
    "AnalysisResultRepository",
    "InstrumentRepository",
    "InstrumentView",
    "ProjectionRepository",
    "Repositories",
    "RunRepository",
    "ScoreRepository",
]
