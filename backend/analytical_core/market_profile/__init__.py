"""Market Profile — deterministic, configurable TPO + Volume Profile (docs/05 §10).

Pure: an ``OHLCVSeries`` (session-scoped ``source_timeframe`` bars) + a
``MarketProfileConfig`` + the session window, in; per-profile-type results out.
The 09:15–15:30 / 30-min / A–M example is derived from the parameters
(``MarketProfileConfig``), not hard-coded.
"""

from __future__ import annotations

from analytical_core.market_profile.config import MarketProfileConfig
from analytical_core.market_profile.engine import (
    ProfileResult,
    build_profile,
    market_profile,
    session_periods,
)
from analytical_core.market_profile.levels import (
    KEY_LEVELS_VERSION,
    Bands,
    KeyLevel,
    KeyLevelsView,
    LevelSession,
    RecentBar,
    build_key_levels,
)
from analytical_core.market_profile.events import (
    MP_EVENTS_VERSION,
    BracketSnapshot,
    DayTypeResult,
    MPCategory,
    MPDayType,
    MPEvent,
    MPEventConfig,
    MPEventResult,
    MPSilhouette,
    MPState,
    MPStrength,
    PriorProfile,
    SessionFacts,
    classify_day_type,
    compute_facts,
    detect_events,
    event_result_to_dict,
    run_event_engine,
)

__all__ = [
    "MarketProfileConfig",
    "ProfileResult",
    "build_profile",
    "market_profile",
    "session_periods",
    # event layer (docs/14)
    "MP_EVENTS_VERSION",
    "BracketSnapshot",
    "DayTypeResult",
    "MPCategory",
    "MPDayType",
    "MPEvent",
    "MPEventConfig",
    "MPEventResult",
    "MPSilhouette",
    "MPState",
    "MPStrength",
    "PriorProfile",
    "SessionFacts",
    "classify_day_type",
    "compute_facts",
    "detect_events",
    "event_result_to_dict",
    "run_event_engine",
    # key levels (docs/05 §10.12)
    "KEY_LEVELS_VERSION",
    "Bands",
    "KeyLevel",
    "KeyLevelsView",
    "LevelSession",
    "RecentBar",
    "build_key_levels",
]
