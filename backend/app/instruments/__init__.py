"""Canonical instrument / contract registry (Phase 2.2).

Turns a provider instrument master (a list of provider-neutral
``InstrumentRecord``s) into canonical ``instruments`` + ``provider_instrument_map``
rows. Deterministic, idempotent, fixture-driven — no network, no auth.

Layering:
  * ``app.providers.<p>.instrument_master``  — provider parsing + normalisation
  * ``contract_key``                          — platform-stable identity (pure)
  * ``validation``                            — deterministic accept / quarantine
  * ``registry``                              — canonical construction + sync
  * ``app.db.repositories.instrument_registry`` — persistence

Universe selection (which contracts become ``is_tracked``) is NOT here — see
``docs/04`` §2.3 / a later ``app/instruments/selection.py``.
"""
