"""LLM-driven next-step decision with hard, code-owned guardrails.

Contract (TASK=NEXT_STEP): the model sees remaining goals, observed facts, executed actions,
known IDs, the allowed action catalog, and the remaining budget. It may only propose actions
from the catalog with parameters built from IDs the run has actually verified. Invalid output
is retried once, then the loop stops safely — never with invented facts.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from graphrag.cypher_templates import TEMPLATES
from graphrag.llm.base import LLMProvider
from graphrag.llm.prompts import NEXT_STEP_SYSTEM, build_next_step_user
from graphrag.models import GraphFact, NextDecision, QueryAction, QueryState

OPTIONAL_FILTER_PARAMS = {"year_from", "year_to", "direction"}
MAX_FACTS_IN_PROMPT = 30
MAX_KNOWN_IDS_IN_PROMPT = 200


def allowed_action_catalog() -> dict[str, list[str]]:
    """Action name -> required parameter names, straight from the Cypher whitelist."""
    return {action.value: sorted(template.required_params) for action, template in TEMPLATES.items()}


def collect_known_ids(state: QueryState) -> set[str]:
    """IDs this run has actually verified: linked entities plus every observed fact reference."""
    known: set[str] = set()
    for entity in state.linked_entities:
        if entity.id:
            known.add(entity.id)
    for fact in state.facts:
        if fact.subject_id:
            known.add(fact.subject_id)
        if fact.object_id:
            known.add(fact.object_id)
        known.update(fact.paper_ids)
    return known


def _fact_summary(facts: list[GraphFact]) -> list[dict[str, Any]]:
    summary = []
    for fact in facts[:MAX_FACTS_IN_PROMPT]:
        value = fact.value if isinstance(fact.value, dict) else {}
        summary.append(
            {
                "predicate": fact.predicate,
                "subject_id": fact.subject_id,
                "object_id": fact.object_id,
                "name": value.get("name") or fact.title,
                "year": fact.year,
            }
        )
    return summary


class NextStepDecider:
    def __init__(self, provider: LLMProvider, max_records: int) -> None:
        self.provider = provider
        self.max_records = max_records
        self.catalog = allowed_action_catalog()

    async def decide(
        self,
        question: str,
        intent_name: str,
        requested_fields: list[str],
        state: QueryState,
        new_fact_count: int,
    ) -> tuple[NextDecision, int]:
        """Return (decision, llm_calls).

        Code-owned guards (zero-progress stop, iteration budget, duplicate fingerprints) live
        in the workflow loop; this decider only runs when the plan queue is exhausted and the
        loop may continue. Invalid model output is retried once, then stops the loop safely.
        """
        _ = new_fact_count  # guard already applied by the caller; kept for a stable contract
        known_ids = collect_known_ids(state)
        payload = {
            "question": question,
            "intent": intent_name,
            "requested_fields": requested_fields,
            "executed_actions": [step.action for step in state.executed],
            "executed_fingerprints": sorted(state.seen_fingerprints),
            "goals_remaining": state.goals_remaining,
            "observed_fact_count": len(state.facts),
            "observed_facts": _fact_summary(state.facts),
            "results_truncated": state.truncated,
            "known_ids": sorted(known_ids)[:MAX_KNOWN_IDS_IN_PROMPT],
            "allowed_actions": self.catalog,
            "remaining_budget": state.max_iterations - state.iteration,
        }
        messages = [
            {"role": "system", "content": NEXT_STEP_SYSTEM},
            {"role": "user", "content": build_next_step_user(payload)},
        ]

        for attempt in range(2):
            if attempt == 1:
                messages.append(
                    {"role": "user", "content": "Your prior output was invalid. Return only valid JSON."}
                )
            response = await self.provider.generate(messages, temperature=0, max_tokens=400, json_mode=True)
            decision = self._validated_decision(response.content, known_ids)
            if decision is not None:
                return decision, attempt + 1

        # Contract: never invent facts on invalid output — stop safely with an explicit reason.
        return (
            NextDecision(
                sufficient=False,
                missing_goals=list(state.goals_remaining),
                reason_code="invalid_decision",
            ),
            2,
        )

    def _validated_decision(self, content: str, known_ids: set[str]) -> NextDecision | None:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        normalized = self._normalize_keys(payload)
        try:
            decision = NextDecision.model_validate(normalized)
        except ValidationError:
            return None

        if decision.sufficient:
            return decision
        if decision.reason_code in {"no_progress", "missing_entity", "limit_reached"}:
            return decision
        if decision.next_action is None or decision.params is None:
            return None
        if not self._params_are_safe(decision.next_action, decision.params, known_ids):
            return None
        return decision

    @staticmethod
    def _normalize_keys(payload: dict[str, Any]) -> dict[str, Any]:
        """Map the free-form model contract onto the strict NextDecision schema."""
        normalized = dict(payload)
        normalized.pop("reason", None)
        if "reason_code" not in normalized:
            if normalized.get("sufficient"):
                normalized["reason_code"] = "enough"
            elif normalized.get("next_action"):
                normalized["reason_code"] = "continue"
            else:
                normalized["reason_code"] = "no_progress"
        if normalized.get("ask_clarification"):
            normalized["reason_code"] = "missing_entity"
            normalized["sufficient"] = False
            normalized.pop("ask_clarification", None)
        return normalized

    def _params_are_safe(self, action: QueryAction, params: dict[str, Any], known_ids: set[str]) -> bool:
        required = TEMPLATES[action].required_params
        provided = set(params.keys())
        if not required <= provided:
            return False
        if not provided <= (required | OPTIONAL_FILTER_PARAMS):
            return False
        for key, value in params.items():
            if key in OPTIONAL_FILTER_PARAMS:
                continue
            if not isinstance(value, str) or value not in known_ids:
                return False
        year_from = params.get("year_from")
        year_to = params.get("year_to")
        for year in (year_from, year_to):
            if year is not None and not (isinstance(year, int) and 1900 <= year <= 2100):
                return False
        direction = params.get("direction")
        return direction is None or direction in {"outgoing", "incoming", "both"}
