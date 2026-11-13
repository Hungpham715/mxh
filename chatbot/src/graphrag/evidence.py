"""Normalize graph rows into stable facts and server-owned citations."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import ValidationError

from graphrag.models import Citation, GraphFact


class EvidenceNormalizer:
    def normalize(self, records: list[dict[str, Any]]) -> list[GraphFact]:
        facts: list[GraphFact] = []
        for record in records:
            canonical = json.dumps(record, sort_keys=True, ensure_ascii=False, default=str)
            fact_id = hashlib.sha256(canonical.encode()).hexdigest()[:20]
            try:
                fact = GraphFact(
                    fact_id=fact_id,
                    subject_id=str(record["subject_id"]),
                    predicate=str(record["predicate"]),
                    object_id=str(record["object_id"]) if record.get("object_id") is not None else None,
                    value=record.get("value"),
                    paper_ids=[str(item) for item in (record.get("paper_ids") or [])],
                    source_url=record.get("source_url"),
                    year=record.get("year"),
                    title=record.get("title"),
                    claim_type="graph_fact",
                    limitations=self._limitations(str(record["predicate"])),
                )
            except (KeyError, ValidationError, TypeError, ValueError):
                continue
            facts.append(fact)
        return facts

    @staticmethod
    def _limitations(predicate: str) -> list[str]:
        if "AFFILIAT" in predicate:
            return ["Affiliation is evidenced on a specific paper; it is not current employment."]
        if "CIT" in predicate:
            return ["Citation coverage is limited to papers inside this sampled corpus."]
        if "TOPIC" in predicate or "LABELLED" in predicate:
            return ["Topic labels are precision-first and missing labels do not imply absence."]
        return ["Result is limited to the sampled 2023-2025 corpus."]


def build_citations(facts: list[GraphFact]) -> list[Citation]:
    by_paper: dict[str, dict[str, Any]] = {}
    for fact in facts:
        sources = []
        if isinstance(fact.value, dict):
            value_sources = fact.value.get("sources", [])
            if isinstance(value_sources, list):
                sources = value_sources
        for source in sources:
            if not isinstance(source, dict):
                continue
            paper_id = source.get("paper_id")
            title = source.get("title")
            url = source.get("url")
            if not all(isinstance(item, str) and item for item in (paper_id, title, url)):
                continue
            current = by_paper.setdefault(paper_id, {"title": title, "url": url, "claim_ids": []})
            current["claim_ids"].append(fact.fact_id)

        if fact.source_url and fact.paper_ids:
            paper_id = fact.paper_ids[0]
            title = fact.title or paper_id
            current = by_paper.setdefault(
                paper_id,
                {"title": title, "url": fact.source_url, "claim_ids": []},
            )
            current["claim_ids"].append(fact.fact_id)

    citations: list[Citation] = []
    for paper_id, data in sorted(by_paper.items()):
        try:
            citations.append(
                Citation(
                    paper_id=paper_id,
                    title=data["title"],
                    url=data["url"],
                    claim_ids=sorted(set(data["claim_ids"])),
                )
            )
        except ValidationError:
            continue
    return citations
