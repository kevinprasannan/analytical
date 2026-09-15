"""app — FastAPI application, persistence, provider adapters, ingestion, worker.

Depends on ``analytical_core``; the reverse never holds (docs/02 §2).
Phase 1 is scaffolding: the pipeline, persistence, provider seam, validation
gate and worker lifecycle exist; analytical formulas and real Upstox integration
do not.
"""
