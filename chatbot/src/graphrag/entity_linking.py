"""Exact ID/name linking followed by bounded in-memory fuzzy matching."""

from __future__ import annotations

import re
import unicodedata

from rapidfuzz import fuzz, process

from graphrag.graph.base import EntityRecord, GraphRepository
from graphrag.models import CandidateEntity, EntityMention, LinkedEntity


def normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


QUOTED_SPAN = re.compile(r"[\"“”'‘’«](.{3,300}?)[\"“”'’»]")
SPOT_LABELS = ("Paper", "Author", "Institution", "Topic")
MAX_SPAN_TOKENS = 12


class EntityLinker:
    def __init__(self, repository: GraphRepository, score_threshold: float, score_margin: float) -> None:
        self.repository = repository
        self.score_threshold = score_threshold
        self.score_margin = score_margin

    async def link(self, mention: EntityMention) -> LinkedEntity | None:
        catalog = await self.repository.entity_catalog()
        allowed = [record for record in catalog if mention.type == "Unknown" or record.label == mention.type]
        if not allowed:
            return None

        exact_id = [record for record in allowed if record.id.casefold() == mention.text.casefold()]
        if exact_id:
            return self._linked(exact_id[0], 100)

        normalized_text = normalize_name(mention.text)
        exact_names = [record for record in allowed if normalize_name(record.name) == normalized_text]
        if len(exact_names) == 1:
            return self._linked(exact_names[0], 100)
        if len(exact_names) > 1:
            candidates = [self._candidate(record, 100) for record in exact_names[:3]]
            return LinkedEntity(
                label=exact_names[0].label,
                id="",
                name=mention.text,
                score=100,
                ambiguous_candidates=candidates,
            )

        choices = {str(index): normalize_name(record.name) for index, record in enumerate(allowed)}
        matches = process.extract(normalized_text, choices, scorer=fuzz.WRatio, limit=3)
        if not matches:
            return None
        best_text, best_score, best_key = matches[0]
        _ = best_text
        if best_score < self.score_threshold:
            return None
        second_score = matches[1][1] if len(matches) > 1 else 0
        if best_score - second_score < self.score_margin:
            candidates = [self._candidate(allowed[int(key)], score) for _, score, key in matches]
            return LinkedEntity(
                label=allowed[int(best_key)].label,
                id="",
                name=mention.text,
                score=best_score,
                ambiguous_candidates=candidates,
            )
        return self._linked(allowed[int(best_key)], best_score)

    async def spot(self, text: str) -> list[EntityMention]:
        """Find catalog names that literally occur in `text` (exact normalized match).

        Used only to repair a parse whose entities are missing or not grounded in the question.
        Quoted spans are tried first (paper titles); then the longest non-overlapping token
        n-grams that equal a node name. This is entity linking, not intent classification.
        """
        catalog = await self.repository.entity_catalog()
        by_name: dict[str, set[str]] = {}
        for record in catalog:
            if record.label in SPOT_LABELS:
                by_name.setdefault(normalize_name(record.name), set()).add(record.label)

        found: list[EntityMention] = []
        for span in QUOTED_SPAN.findall(text):
            labels = by_name.get(normalize_name(span))
            if labels:
                found.append(EntityMention(text=span.strip(), type=_preferred_label(labels)))
        if found:
            return found

        tokens = re.findall(r"[\w][\w\-\.']*", text)
        used = [False] * len(tokens)
        for size in range(min(MAX_SPAN_TOKENS, len(tokens)), 1, -1):
            for start in range(0, len(tokens) - size + 1):
                if any(used[start : start + size]):
                    continue
                candidate = " ".join(tokens[start : start + size])
                labels = by_name.get(normalize_name(candidate))
                if labels:
                    found.append(EntityMention(text=candidate, type=_preferred_label(labels)))
                    for index in range(start, start + size):
                        used[index] = True
        return found

    async def link_all(self, mentions: list[EntityMention]) -> list[LinkedEntity | None]:
        linked: list[LinkedEntity | None] = []
        for mention in mentions:
            linked.append(await self.link(mention))
        return linked

    @staticmethod
    def _candidate(record: EntityRecord, score: float) -> CandidateEntity:
        return CandidateEntity(id=record.id, label=record.label, name=record.name, score=score)

    @staticmethod
    def _linked(record: EntityRecord, score: float) -> LinkedEntity:
        return LinkedEntity(
            label=record.label,
            id=record.id,
            name=record.name,
            score=score,
            identity_status=record.identity_status,
        )


def _preferred_label(labels: set[str]) -> str:
    for label in SPOT_LABELS:
        if label in labels:
            return label
    return "Unknown"
