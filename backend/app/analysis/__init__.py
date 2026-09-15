"""ANALYZE phase.

For each tracked instrument the applicability matrix (docs/04 §4) is evaluated,
then each planned ``(analysis_key, scope)`` is computed by the deterministic
``analytical_core`` engine (indicators + Market Profile) and written to
``analysis_results`` (with provenance columns) and the ``current_analysis_results``
projection under the current run. ``NOT_APPLICABLE`` / ``INSUFFICIENT_DATA`` plans
get an explicit no-engine row (``analytical_core.results.matrix_status_result``).
"""
