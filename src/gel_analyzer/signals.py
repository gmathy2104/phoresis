"""Signal handlers for gel_analyzer.

Phoresis is a single-purpose analyzer with no external sample registry, so
this module is intentionally empty in v1.

If a future app reintroduces a sample registry (a new ProcessSample-like
model in some other Phoresis app), wire it back via `post_save` on
`gel_analyzer.Lane` and the lane's new FK / GenericRelation. The original
ds-hub-django implementation lives at the project root (commit
1a2b523^ : `gel_analyzer/signals.py`) for reference.
"""
