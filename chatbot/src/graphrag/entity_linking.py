"""Exact ID/name linking followed by bounded in-memory fuzzy matching.

Also owns `rescue_mentions`: a deterministic, catalog-grounded fallback that recovers entity
mentions the weak base model failed to extract. It only matches names that appear VERBATIM in
the question (or, for explicit pronoun references, in the conversation history) against the
live graph catalog — it never invents entities. Every rescue is labelled in the response meta.
"""

from __future__ import annotations

import re
import unicodedata

from rapidfuzz import fuzz, process

from graphrag.graph.base import EntityRecord, GraphRepository
from graphrag.models import CandidateEntity, EntityMention, LinkedEntity

# intent value -> (required mention label, required count); entity-free intents map to None.
INTENT_REQUIRED_MENTIONS: dict[str, tuple[str, int] | None] = {
    "author_papers": ("Author", 1),
    "coauthors": ("Author", 1),
    "author_affiliations": ("Author", 1),
    "coauthor_affiliations": ("Author", 1),
    "shared_papers": ("Author", 2),
    "author_path": ("Author", 2),
    "paper_authors": ("Paper", 1),
    "paper_venue": ("Paper", 1),
    "paper_citations": ("Paper", 1),
    "topic_papers": ("Topic", 1),
    "org_collaborations": ("Institution", 1),
    "network_top": None,
    "unknown": None,
}

PRONOUN_MARKERS = (
    "người đó",
    "tác giả đó",
    "tác giả này",
    "người này",
    "ông ấy",
    "bà ấy",
    "bài đó",
    "bài báo đó",
    "bài này",
    "của họ",
    "that author",
    "the author",
)

MIN_RESCUE_NAME_LENGTH = 4


def normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


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

    async def link_all(self, mentions: list[EntityMention]) -> list[LinkedEntity | None]:
        linked: list[LinkedEntity | None] = []
        for mention in mentions:
            linked.append(await self.link(mention))
        return linked

    async def rescue_mentions(
        self, intent_value: str, question: str, history: list[dict[str, str]]
    ) -> list[EntityMention]:
        """Deterministic catalog fallback: recover entity spans the weak base model missed.

        Fires only for a concrete intent with a known required label/count. Matches catalog
        names that appear VERBATIM (normalized) in the question; for two-entity intents it
        takes the two longest distinct matches. If the question only refers by pronoun, it
        looks for the most recent catalog name in history. Never invents an entity: everything
        returned is a real catalog name found in the input text.
        """
        required = INTENT_REQUIRED_MENTIONS.get(intent_value)
        if required is None:
            return []
        label, count = required

        catalog = await self.repository.entity_catalog()
        same_label = [record for record in catalog if record.label == label]
        if not same_label:
            return []

        question_norm = normalize_name(question)
        matches = self._longest_catalog_matches(question_norm, same_label, count)
        if len(matches) < count and self._refers_by_pronoun(question_norm):
            history_matches = self._recent_history_matches(history, same_label, count - len(matches))
            for mention in history_matches:
                if mention.text not in {m.text for m in matches}:
                    matches.append(mention)
        return matches[:count]

    @staticmethod
    def _longest_catalog_matches(
        text_norm: str, records: list[EntityRecord], count: int
    ) -> list[EntityMention]:
        """Find up to `count` distinct catalog names present in text_norm, longest first.

        Longest-first avoids picking a short name that is a substring of a longer real match.
        """
        candidates: list[tuple[int, EntityRecord]] = []
        for record in records:
            name_norm = normalize_name(record.name)
            if len(name_norm) < MIN_RESCUE_NAME_LENGTH:
                continue
            if name_norm in text_norm:
                candidates.append((len(name_norm), record))
        candidates.sort(key=lambda item: (-item[0], item[1].name))

        chosen: list[EntityMention] = []
        chosen_names: set[str] = set()
        for _, record in candidates:
            name_norm = normalize_name(record.name)
            if name_norm in chosen_names:
                continue
            # Skip a candidate fully contained in an already-chosen longer name.
            if any(name_norm in chosen_name for chosen_name in chosen_names):
                continue
            chosen_names.add(name_norm)
            chosen.append(EntityMention(text=record.name, type=record.label))
            if len(chosen) >= count:
                break
        return chosen

    @staticmethod
    def _refers_by_pronoun(question_norm: str) -> bool:
        return any(marker in question_norm for marker in PRONOUN_MARKERS)

    @staticmethod
    def _recent_history_matches(
        history: list[dict[str, str]], records: list[EntityRecord], count: int
    ) -> list[EntityMention]:
        """Most-recent-first catalog names appearing in prior user turns (pronoun antecedents)."""
        by_name = {
            normalize_name(record.name): record
            for record in records
            if len(record.name) >= MIN_RESCUE_NAME_LENGTH
        }
        found: list[EntityMention] = []
        seen: set[str] = set()
        for message in reversed(history):
            if message.get("role") != "user":
                continue
            content_norm = normalize_name(str(message.get("content", "")))
            for name_norm, record in by_name.items():
                if name_norm in content_norm and name_norm not in seen:
                    seen.add(name_norm)
                    found.append(EntityMention(text=record.name, type=record.label))
                    if len(found) >= count:
                        return found
        return found

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
