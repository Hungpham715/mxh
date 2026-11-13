"""Map validated intents and linked IDs to query catalog steps."""

from __future__ import annotations

from graphrag.models import IntentName, LinkedEntity, QueryAction, QueryIntent, QueryStep

EXPECTED_FIELDS = {
    action: ["subject_id", "predicate", "object_id", "value", "paper_ids"] for action in QueryAction
}


class Planner:
    def __init__(self, max_records: int) -> None:
        self.max_records = max_records

    def plan(self, intent: QueryIntent, linked: list[LinkedEntity]) -> list[QueryStep]:
        by_label: dict[str, list[LinkedEntity]] = {}
        for entity in linked:
            by_label.setdefault(entity.label, []).append(entity)

        if intent.intent == IntentName.UNKNOWN:
            return []
        if intent.intent == IntentName.NETWORK_TOP:
            return [self._step(QueryAction.NETWORK_TOP, {})]

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

        steps = [self._step(action, params)]
        if intent.intent == IntentName.AUTHOR_PAPERS and "affiliations" in intent.requested_fields:
            steps.append(self._step(QueryAction.AUTHOR_AFFILIATIONS, {"author_id": params["author_id"]}))
        return steps

    def _step(self, action: QueryAction, params: dict[str, object]) -> QueryStep:
        return QueryStep(
            action=action,
            params=params,
            expected_fields=EXPECTED_FIELDS[action],
            limit=self.max_records,
        )

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
