"""Worker: one execution cycle == one ``analysis_runs`` row covering
INGEST -> ANALYZE -> SCORE -> projection update (docs/02 §4, docs/03 §5.3).

Covers the run lifecycle/state-machine and its failure handling, the real
ANALYZE/SCORE engines, single-flight, the ``run-completed`` hook
(``app/worker/hooks.py``), and the APScheduler loop (``app/worker/scheduler.py``).
"""
