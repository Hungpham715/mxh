"""Code-owned hard guards for the retrieval loop.

These rules run without any LLM involvement and can never be overridden by model output:
a step that produced no new facts while the plan queue is exhausted means no progress, and
the iteration budget is absolute. Sufficiency of the *answer* is decided by the validated
TASK=NEXT_STEP model call in `graphrag.next_step`, never by fingerprint bookkeeping alone.
"""

from __future__ import annotations

from graphrag.models import QueryState


def hard_stop_reason(state: QueryState, new_fact_count: int, queue_empty: bool) -> str | None:
    """Return a stop reason when code must halt the loop, else None to keep going."""
    if new_fact_count == 0 and queue_empty:
        return "no_progress"
    if state.iteration >= state.max_iterations:
        return "max_iterations"
    return None
