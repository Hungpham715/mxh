"""Map validated intents to catalog steps, and validate follow-up proposals.

The first step comes from the parsed intent. Follow-up steps are proposed by the model
(TASK=NEXT_STEP) and must pass `validate_proposal`: the action must be in the catalog,
params must be exactly the template's params, and every ID must already be known from a
linked entity or an observed fact. If the model output is unusable, `contract_proposal`
derives the next step from the same contract (explicitly labelled `contract_fallback`).
"""

from __future__ import annotations

from typing import Any

from graphrag.cypher_templates import ALLOWED_PARAMS, get_template
from graphrag.models import (
    GraphFact,
    IntentName,
    LinkedEntity,
    QueryAction,
    QueryIntent,
    QueryStep,
)

EXPECTED_FIELDS = {
    action: ["subject_id", "predicate", "object_id", "value", "paper_ids"] for action in QueryAction
}

# Which label an action's object_id has. Used to learn new IDs from observed facts.
OBJECT_LABEL: dict[QueryAction, str] = {
    QueryAction.AUTHOR_PAPERS: "Paper",
    QueryAction.COAUTHORS: "Author",
    QueryAction.SHARED_PAPERS: "Author",
    QueryAction.AUTHOR_AFFILIATIONS: "Institution",
    QueryAction.COAUTHOR_AFFILIATIONS: "Institution",
    QueryAction.PAPER_AUTHORS: "Author",
    QueryAction.TOPIC_PAPERS: "Paper",
    QueryAction.PAPER_VENUE: "Venue",
    QueryAction.PAPER_CITATIONS: "Paper",
    QueryAction.ORG_COLLABORATIONS: "Institution",
    QueryAction.AUTHOR_PATH: "Author",
    QueryAction.NETWORK_TOP: "Author",
}

# Label each ID parameter must have.
PARAM_LABEL = {
    "author_id": "Author",
    "other_author_id": "Author",
    "paper_id": "Paper",
    "topic_id": "Topic",
    "institution_id": "Institution",
}

# requested field -> (follow-up action, label of the ID it needs)
GOAL_ACTIONS: dict[str, tuple[QueryAction, str]] = {
    "venue": (QueryAction.PAPER_VENUE, "Paper"),
    "authors": (QueryAction.PAPER_AUTHORS, "Paper"),
    "citations": (QueryAction.PAPER_CITATIONS, "Paper"),
    "affiliations": (QueryAction.AUTHOR_AFFILIATIONS, "Author"),
    "coauthors": (QueryAction.COAUTHORS, "Author"),
    "papers": (QueryAction.AUTHOR_PAPERS, "Author"),
}
GOAL_FOR_ACTION = {action: goal for goal, (action, _) in GOAL_ACTIONS.items()}


class Planner:
    def __init__(self, max_records: int) -> None:
        self.max_records = max_records

    def plan(self, intent: QueryIntent, linked: list[LinkedEntity]) -> list[QueryStep]:
        """Return the single first step for the intent (empty when nothing is plannable)."""
        by_label: dict[str, list[LinkedEntity]] = {}
        for entity in linked:
            by_label.setdefault(entity.label, []).append(entity)

        if intent.intent == IntentName.UNKNOWN:
            return []
        if intent.intent == IntentName.NETWORK_TOP:
            return [self.step(QueryAction.NETWORK_TOP, {})]

        action = QueryAction(intent.intent.value)
        params: dict[str, object] = {}
        if action in {
            QueryAction.AUTHOR_PAPERS,
            QueryAction.COAUTHORS,
            QueryAction.AUTHOR_AFFILIATIONS,
            QueryAction.COAUTHOR_AFFILIATIONS,
        }:
            params["author_id"] = self._one(by_label, "Author").id
        elif action in {QueryAction.SHARED_PAPERS, QueryAction.AUTHOR_PATH}:
            authors = self._many(by_label, "Author", 2)
            params.update(author_id=authors[0].id, other_author_id=authors[1].id)
        elif action in {QueryAction.PAPER_AUTHORS, QueryAction.PAPER_VENUE, QueryAction.PAPER_CITATIONS}:
            params["paper_id"] = self._one(by_label, "Paper").id
        elif action == QueryAction.TOPIC_PAPERS:
            params["topic_id"] = self._one(by_label, "Topic").id
        elif action == QueryAction.ORG_COLLABORATIONS:
            params["institution_id"] = self._one(by_label, "Institution").id

        if action in {QueryAction.AUTHOR_PAPERS, QueryAction.TOPIC_PAPERS}:
            params["year_from"] = intent.filters.year_from
            params["year_to"] = intent.filters.year_to
        if action == QueryAction.PAPER_CITATIONS:
            params["direction"] = intent.filters.citation_direction
        return [self.step(action, params)]

    @staticmethod
    def goals(intent: QueryIntent) -> list[str]:
        """Goals = the main intent plus requested extra fields not already covered by it."""
        main = f"main:{intent.intent.value}"
        extra = []
        for field in intent.requested_fields:
            if field not in GOAL_ACTIONS:
                continue
            action, _ = GOAL_ACTIONS[field]
            if action.value == intent.intent.value:
                continue
            if field not in extra:
                extra.append(field)
        return [main, *extra]

    def step(self, action: QueryAction, params: dict[str, object], offset: int = 0) -> QueryStep:
        return QueryStep(
            action=action,
            params=params,
            expected_fields=EXPECTED_FIELDS[action],
            limit=self.max_records,
            offset=offset,
        )

    @staticmethod
    def known_ids(
        linked: list[LinkedEntity], executed: list[QueryStep], facts: list[GraphFact]
    ) -> dict[str, list[str]]:
        """IDs the loop is allowed to use, grouped by label, in first-seen order."""
        known: dict[str, list[str]] = {}

        def add(label: str, node_id: str | None) -> None:
            if not node_id:
                return
            bucket = known.setdefault(label, [])
            if node_id not in bucket:
                bucket.append(node_id)

        for entity in linked:
            add(entity.label, entity.id)
        _ = executed
        for fact in facts:
            for paper_id in fact.paper_ids:
                add("Paper", paper_id)
            action = _action_for_predicate(fact.predicate)
            if action is not None:
                add(OBJECT_LABEL[action], fact.object_id)
        return known

    def validate_proposal(
        self,
        action_name: Any,
        params: Any,
        known: dict[str, list[str]],
        executed_fingerprints: set[str],
    ) -> tuple[QueryStep | None, str]:
        try:
            action = QueryAction(str(action_name))
        except ValueError:
            return None, "action_not_in_catalog"
        if not isinstance(params, dict):
            return None, "params_not_object"
        template = get_template(action)
        if set(params) - ALLOWED_PARAMS[action]:
            return None, "unexpected_params"
        if template.required_params - set(params):
            return None, "missing_required_params"
        for name, value in params.items():
            if name in PARAM_LABEL:
                if not isinstance(value, str) or value not in known.get(PARAM_LABEL[name], []):
                    return None, f"unknown_id:{name}"
            elif name in {"year_from", "year_to"}:
                if value is not None and not isinstance(value, int):
                    return None, f"bad_type:{name}"
            elif name == "direction" and value not in {"outgoing", "incoming", "both"}:
                return None, "bad_direction"
        step = self.step(action, dict(params))
        if step.fingerprint in executed_fingerprints:
            return None, "duplicate_step"
        return step, "ok"

    def pending_for_goal(
        self, goal: str, known: dict[str, list[str]], executed_fingerprints: set[str]
    ) -> int:
        """How many known IDs still lack the goal's follow-up action."""
        if goal not in GOAL_ACTIONS:
            return 0
        return 1 if self.contract_proposal([goal], known, executed_fingerprints) is not None else 0

    def contract_proposal(
        self,
        goals_remaining: list[str],
        known: dict[str, list[str]],
        executed_fingerprints: set[str],
    ) -> QueryStep | None:
        """Deterministic next step for the first remaining goal (used only if the model fails)."""
        for goal in goals_remaining:
            if goal not in GOAL_ACTIONS:
                continue
            action, label = GOAL_ACTIONS[goal]
            param_name = next(
                name
                for name, value in PARAM_LABEL.items()
                if value == label and name in get_template(action).required_params
            )
            for node_id in known.get(label, []):
                params: dict[str, object] = {param_name: node_id}
                if action == QueryAction.PAPER_CITATIONS:
                    params["direction"] = "both"
                if action == QueryAction.AUTHOR_PAPERS:
                    params.update(year_from=None, year_to=None)
                candidate = self.step(action, params)
                if candidate.fingerprint not in executed_fingerprints:
                    return candidate
        return None

    @staticmethod
    def _one(by_label: dict[str, list[LinkedEntity]], label: str) -> LinkedEntity:
        entities = by_label.get(label, [])
        if not entities:
            raise ValueError(f"intent requires one linked {label}")
        return entities[0]

    @staticmethod
    def _many(by_label: dict[str, list[LinkedEntity]], label: str, count: int) -> list[LinkedEntity]:
        entities = by_label.get(label, [])
        if len(entities) < count:
            raise ValueError(f"intent requires {count} linked {label} entities")
        return entities[:count]


_PREDICATE_ACTION = {
    "AUTHORED": QueryAction.AUTHOR_PAPERS,
    "COAUTHORED_WITH": QueryAction.COAUTHORS,
    "SHARED_PAPER_WITH": QueryAction.SHARED_PAPERS,
    "AFFILIATED_WITH_ON_PAPER": QueryAction.AUTHOR_AFFILIATIONS,
    "COAUTHOR_AFFILIATION_ON_SHARED_PAPER": QueryAction.COAUTHOR_AFFILIATIONS,
    "FIRST_AUTHOR_OF": QueryAction.PAPER_AUTHORS,
    "OTHER_AUTHOR_OF": QueryAction.PAPER_AUTHORS,
    "HAS_LABELLED_PAPER": QueryAction.TOPIC_PAPERS,
    "APPEARS_IN": QueryAction.PAPER_VENUE,
    "CITES_IN_CORPUS": QueryAction.PAPER_CITATIONS,
    "CITED_BY_IN_CORPUS": QueryAction.PAPER_CITATIONS,
    "ORG_COAUTHORED_WITH": QueryAction.ORG_COLLABORATIONS,
    "COAUTHOR_PATH": QueryAction.AUTHOR_PATH,
    "RANKED_BY_COAUTHOR_COUNT": QueryAction.NETWORK_TOP,
}


def _action_for_predicate(predicate: str) -> QueryAction | None:
    return _PREDICATE_ACTION.get(predicate)
