"""Generate candidate questions from existing graph entities.

Two modes:

* Legacy (``per_action == 0``): the twelve canonical query templates over a single fixed set
  of entities. Kept for deterministic fake-provider plumbing tests.
* Sampling (``per_action > 0``): draws up to ``per_action`` entities per query template from
  the live catalog so the training set is large and diverse.

Every case carries the runtime-aligned gold fields (``entity_mentions``, ``filters``,
``verified_facts``) so ``build_sft`` can reproduce the exact PARSE/ANSWER prompts the chatbot
uses at inference time. Cases are candidates only and stay ``needs_review`` until reviewed.
"""

from __future__ import annotations

import argparse
import asyncio
import random
from pathlib import Path
from typing import Any

from datasets.io import write_models
from datasets.schema import (
    EntityMention,
    ExpectedCitations,
    ExpectedFacts,
    ExpectedQuery,
    QuestionCase,
    ReviewStatus,
)
from graphrag.evidence import EvidenceNormalizer, build_citations
from graphrag.graph.fake_graph import FakeGraphRepository
from graphrag.graph.neo4j_readonly import Neo4jReadOnlyRepository
from graphrag.models import QueryAction, QueryStep
from graphrag.settings import Settings

QUESTION_TEMPLATES = {
    QueryAction.AUTHOR_PAPERS: "{a} có những bài báo nào trong corpus?",
    QueryAction.COAUTHORS: "Đồng tác giả của {a} là ai?",
    QueryAction.SHARED_PAPERS: "{a} và {b} có bài báo chung nào?",
    QueryAction.AUTHOR_AFFILIATIONS: "{a} gắn với tổ chức nào theo từng bài báo?",
    QueryAction.COAUTHOR_AFFILIATIONS: "Tổ chức của đồng tác giả {a} trên bài chung là gì?",
    QueryAction.PAPER_AUTHORS: "Ai là tác giả của {p}?",
    QueryAction.TOPIC_PAPERS: "Các bài đã gắn nhãn chủ đề {t} là gì?",
    QueryAction.PAPER_VENUE: "Bài {p} xuất hiện ở venue nào?",
    QueryAction.PAPER_CITATIONS: "Bài {p} được trích dẫn bởi bài nào trong corpus?",
    QueryAction.ORG_COLLABORATIONS: "{i} hợp tác với tổ chức nào trong corpus?",
    QueryAction.AUTHOR_PATH: "Đường đồng tác giả giữa {a} và {b} là gì?",
    QueryAction.NETWORK_TOP: "Top tác giả theo số đồng tác giả riêng biệt là ai?",
}

# Default filters mirror graphrag.models.QueryFilters; citation_direction is the only one a
# template varies today.
DEFAULT_FILTERS: dict[str, Any] = {
    "year_from": None,
    "year_to": None,
    "topic_id": None,
    "citation_direction": "both",
}


class Spec:
    """One planned question: the action, its query params, and the gold parse fields."""

    def __init__(
        self,
        action: QueryAction,
        params: dict[str, Any],
        values: dict[str, str],
        mentions: list[EntityMention],
        filters: dict[str, Any] | None = None,
    ) -> None:
        self.action = action
        self.params = params
        self.values = values
        self.mentions = mentions
        self.filters = filters if filters is not None else dict(DEFAULT_FILTERS)


def _author_mention(author) -> EntityMention:
    return EntityMention(text=author.name, type="Author")


def _legacy_specs(authors, papers, topics, institutions) -> list[Spec]:
    """The twelve canonical templates over the first entities (deterministic plumbing)."""
    if len(authors) < 2 or not papers or not topics or not institutions:
        raise ValueError("graph needs at least 2 authors and one paper/topic/institution")
    author_a, author_b = authors[0], authors[1]
    paper = papers[0]
    topic = topics[0]
    institution = institutions[0]
    a = {"a": author_a.name}
    ab = {"a": author_a.name, "b": author_b.name}
    p = {"p": paper.name}
    t = {"t": topic.name}
    i = {"i": institution.name}
    mention_a = [_author_mention(author_a)]
    mention_ab = [_author_mention(author_a), _author_mention(author_b)]
    mention_paper = [EntityMention(text=paper.name, type="Paper")]
    mention_topic = [EntityMention(text=topic.name, type="Topic")]
    mention_inst = [EntityMention(text=institution.name, type="Institution")]
    author_params = {"author_id": author_a.id}
    pair_params = {"author_id": author_a.id, "other_author_id": author_b.id}
    return [
        Spec(QueryAction.AUTHOR_PAPERS, {**author_params, "year_from": None, "year_to": None}, a, mention_a),
        Spec(QueryAction.COAUTHORS, dict(author_params), a, mention_a),
        Spec(QueryAction.SHARED_PAPERS, dict(pair_params), ab, mention_ab),
        Spec(QueryAction.AUTHOR_AFFILIATIONS, dict(author_params), a, mention_a),
        Spec(QueryAction.COAUTHOR_AFFILIATIONS, dict(author_params), a, mention_a),
        Spec(QueryAction.PAPER_AUTHORS, {"paper_id": paper.id}, p, mention_paper),
        Spec(
            QueryAction.TOPIC_PAPERS,
            {"topic_id": topic.id, "year_from": None, "year_to": None},
            t,
            mention_topic,
        ),
        Spec(QueryAction.PAPER_VENUE, {"paper_id": paper.id}, p, mention_paper),
        Spec(QueryAction.PAPER_CITATIONS, {"paper_id": paper.id, "direction": "both"}, p, mention_paper),
        Spec(QueryAction.ORG_COLLABORATIONS, {"institution_id": institution.id}, i, mention_inst),
        Spec(QueryAction.AUTHOR_PATH, dict(pair_params), ab, mention_ab),
        Spec(QueryAction.NETWORK_TOP, {}, {}, []),
    ]


def _pick(items: list, count: int, rng: random.Random) -> list:
    """Return up to `count` distinct items in a reproducible shuffled order."""
    if count <= 0 or not items:
        return []
    shuffled = list(items)
    rng.shuffle(shuffled)
    return shuffled[:count]


def _sampled_specs(authors, papers, topics, institutions, per_action: int, rng: random.Random) -> list[Spec]:
    """Expand every template across many entities to build a large, diverse candidate set."""
    specs: list[Spec] = []

    for author in _pick(authors, per_action, rng):
        mention = [_author_mention(author)]
        values = {"a": author.name}
        specs.append(
            Spec(
                QueryAction.AUTHOR_PAPERS,
                {"author_id": author.id, "year_from": None, "year_to": None},
                values,
                mention,
            )
        )
        specs.append(Spec(QueryAction.COAUTHORS, {"author_id": author.id}, values, mention))
        specs.append(Spec(QueryAction.AUTHOR_AFFILIATIONS, {"author_id": author.id}, values, mention))
        specs.append(Spec(QueryAction.COAUTHOR_AFFILIATIONS, {"author_id": author.id}, values, mention))

    for paper in _pick(papers, per_action, rng):
        mention = [EntityMention(text=paper.name, type="Paper")]
        values = {"p": paper.name}
        specs.append(Spec(QueryAction.PAPER_AUTHORS, {"paper_id": paper.id}, values, mention))
        specs.append(Spec(QueryAction.PAPER_VENUE, {"paper_id": paper.id}, values, mention))
        specs.append(
            Spec(QueryAction.PAPER_CITATIONS, {"paper_id": paper.id, "direction": "both"}, values, mention)
        )

    for topic in _pick(topics, per_action, rng):
        specs.append(
            Spec(
                QueryAction.TOPIC_PAPERS,
                {"topic_id": topic.id, "year_from": None, "year_to": None},
                {"t": topic.name},
                [EntityMention(text=topic.name, type="Topic")],
            )
        )

    for institution in _pick(institutions, per_action, rng):
        specs.append(
            Spec(
                QueryAction.ORG_COLLABORATIONS,
                {"institution_id": institution.id},
                {"i": institution.name},
                [EntityMention(text=institution.name, type="Institution")],
            )
        )

    # Author pairs for the two-author templates.
    pair_pool = _pick(authors, per_action * 2, rng)
    for index in range(0, len(pair_pool) - 1, 2):
        author_a, author_b = pair_pool[index], pair_pool[index + 1]
        mentions = [_author_mention(author_a), _author_mention(author_b)]
        values = {"a": author_a.name, "b": author_b.name}
        params = {"author_id": author_a.id, "other_author_id": author_b.id}
        specs.append(Spec(QueryAction.SHARED_PAPERS, params, values, mentions))
        specs.append(Spec(QueryAction.AUTHOR_PATH, dict(params), values, mentions))

    # A single network-wide ranking question (no entity to link).
    specs.append(Spec(QueryAction.NETWORK_TOP, {}, {}, []))

    rng.shuffle(specs)
    return specs


def _answer_from_facts(facts) -> str:
    """Join the human-readable object names of each fact, de-duplicated, order preserved."""
    names: list[str] = []
    seen: set[str] = set()
    for fact in facts:
        value = fact.value if isinstance(fact.value, dict) else {}
        name = value.get("name") if isinstance(value, dict) else None
        if name is None:
            name = fact.object_id
        if name is None:
            continue
        text = str(name)
        if text not in seen:
            seen.add(text)
            names.append(text)
    return "; ".join(names)


async def generate(
    provider: str,
    seed: int,
    limit: int,
    execute: bool,
    per_action: int = 0,
) -> list[QuestionCase]:
    if provider == "neo4j" and not execute:
        raise ValueError("Neo4j generation is read-only but still requires explicit --execute")
    repository = await _repository(provider)
    rng = random.Random(seed)
    normalizer = EvidenceNormalizer()
    try:
        catalog = await repository.entity_catalog()
        by_label: dict[str, list] = {}
        for entity in catalog:
            by_label.setdefault(entity.label, []).append(entity)

        authors = by_label.get("Author", [])
        papers = by_label.get("Paper", [])
        topics = by_label.get("Topic", [])
        institutions = by_label.get("Institution", [])

        if per_action > 0:
            specs = _sampled_specs(authors, papers, topics, institutions, per_action, rng)
        else:
            specs = _legacy_specs(authors, papers, topics, institutions)

        cases: list[QuestionCase] = []
        for index, spec in enumerate(specs[:limit], start=1):
            result = await repository.execute(
                QueryStep(action=spec.action, params=spec.params, expected_fields=[], limit=20)
            )
            facts = normalizer.normalize(result.records)
            fact_dicts = [fact.model_dump(mode="json") for fact in facts]
            citations = build_citations(facts)
            answer = _answer_from_facts(facts)
            status = "answered" if facts else "not_found"
            question = QUESTION_TEMPLATES[spec.action].format(**spec.values)
            entity_ids = [str(value) for key, value in spec.params.items() if key.endswith("_id")]

            cases.append(
                QuestionCase(
                    case_id=f"generated-{seed}-{index:05d}",
                    question=question,
                    expected_status=status,
                    expected_query=ExpectedQuery(
                        intent=spec.action.value,
                        entity_ids=entity_ids,
                        params=spec.params,
                    ),
                    expected_facts=ExpectedFacts(
                        predicates=[fact.predicate for fact in facts],
                        object_ids=[fact.object_id for fact in facts if fact.object_id is not None],
                        answer=answer,
                    ),
                    expected_citations=ExpectedCitations(
                        paper_ids=[citation.paper_id for citation in citations],
                        source_urls=[citation.url for citation in citations],
                    ),
                    entity_mentions=spec.mentions,
                    filters=spec.filters,
                    verified_facts=fact_dicts,
                    scope_id="nlpgraph-v1",
                    snapshot_version="synthetic-v1" if provider == "fake" else "live-readonly",
                    template_id=spec.action.value,
                    group_id="|".join(sorted(entity_ids)) or spec.action.value,
                    seed=seed,
                    review_status=ReviewStatus.NEEDS_REVIEW,
                    provenance={"provider": provider, "records": len(result.records)},
                )
            )
        return cases
    finally:
        await repository.close()


async def _repository(provider: str):
    if provider == "fake":
        return FakeGraphRepository()
    settings = Settings.from_env()
    if settings.graph_provider != "neo4j":
        raise ValueError("Set APP_MODE=real and GRAPH_PROVIDER=neo4j for live generation")
    assert settings.neo4j_uri and settings.neo4j_username and settings.neo4j_password
    return Neo4jReadOnlyRepository(
        settings.neo4j_uri,
        settings.neo4j_username,
        settings.neo4j_password,
        settings.neo4j_database,
        settings.neo4j_scope_id,
        settings.entity_cache_ttl_seconds,
        settings.request_timeout_seconds,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["fake", "neo4j"], default="fake")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--per-action",
        type=int,
        default=0,
        help="entities to sample per template (0 = the twelve canonical templates only)",
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    cases = asyncio.run(generate(args.provider, args.seed, args.limit, args.execute, args.per_action))
    count = write_models(args.out, cases)
    print(f"wrote {count} candidate cases to {args.out} (not gold; human review required)")


if __name__ == "__main__":
    main()
