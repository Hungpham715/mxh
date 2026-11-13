"""Hard sufficiency rules keep the model from declaring missing fields complete."""

from __future__ import annotations

from graphrag.models import NextDecision, QueryState


def decide_next(state: QueryState, new_fact_count: int) -> NextDecision:
    if not state.goals_remaining:
        return NextDecision(sufficient=True, reason_code="enough")
    if new_fact_count == 0:
        return NextDecision(
            sufficient=False,
            missing_goals=state.goals_remaining,
            reason_code="no_progress",
        )
    if state.iteration >= state.max_iterations:
        return NextDecision(
            sufficient=False,
            missing_goals=state.goals_remaining,
            reason_code="limit_reached",
        )
    return NextDecision(
        sufficient=False,
        missing_goals=state.goals_remaining,
        reason_code="continue",
    )
