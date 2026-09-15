"""Provider seam (docs/02 §3.2).

All provider-specific code lives behind the protocols in ``base.py``. The rest of
the application asks the active provider what it supports via
``capabilities()`` — it never hard-codes "provider X supports Y" (docs/02 §3.2,
task F).

Phase 1 ships:
  * ``base``        — protocols, DTOs, exceptions
  * ``capabilities``— the explicit capability model + resolution helpers
  * ``registry``    — resolves the single active provider from settings
  * ``validation``  — the machine-readable PV gate (docs/11) + CLI
  * ``stub``        — a deterministic, clearly-synthetic provider for tests/dev
  * ``upstox``      — stub-set ONLY (docs/09 §2.12 allow-list); refuses live calls
                      until the PV gate is cleared. No real integration in Phase 1.
"""
