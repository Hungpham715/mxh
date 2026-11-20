"""Generate candidate questions from existing graph entities.

Two modes:

* Legacy (``per_action == 0``): the canonical query templates over a single fixed set
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
from collections import Counter
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
    QueryAction.PAPER_METHODS: "Bài {p} sử dụng phương pháp nào?",
    QueryAction.METHOD_PAPERS: "Những bài nào sử dụng phương pháp {m}?",
    QueryAction.PAPER_DATASETS: "Bài {p} được đánh giá trên bộ dữ liệu nào?",
    QueryAction.DATASET_PAPERS: "Những bài nào được đánh giá trên {d}?",
    QueryAction.PAPER_TASKS: "Bài {p} giải quyết bài toán nào?",
    QueryAction.TASK_PAPERS: "Những bài nào giải quyết bài toán {k}?",
    QueryAction.METHOD_TRENDS: "Phương pháp nào được dùng nhiều nhất trong corpus?",
}

# Two independently worded surface forms per graph action. Sampling applies both forms across
# hundreds of distinct entities; this adds linguistic diversity without multiplying database
# queries or cloning a handful of facts thousands of times.
QUESTION_VARIANTS = {
    QueryAction.AUTHOR_PAPERS: (
        "{a} có những bài báo nào trong corpus?",
        "Hãy liệt kê các công trình của {a} trong tập dữ liệu.",
    ),
    QueryAction.COAUTHORS: (
        "Đồng tác giả của {a} là ai?",
        "Trong corpus, {a} đã viết bài cùng những ai?",
    ),
    QueryAction.SHARED_PAPERS: (
        "{a} và {b} có bài báo chung nào?",
        "Công trình nào trong corpus có cả {a} và {b}?",
    ),
    QueryAction.AUTHOR_AFFILIATIONS: (
        "{a} gắn với tổ chức nào theo từng bài báo?",
        "Theo bằng chứng trên bài, {a} khai báo các cơ quan nào?",
    ),
    QueryAction.COAUTHOR_AFFILIATIONS: (
        "Tổ chức của đồng tác giả {a} trên bài chung là gì?",
        "Các đồng tác giả của {a} thuộc cơ quan nào trên đúng bài viết chung?",
    ),
    QueryAction.PAPER_AUTHORS: (
        "Ai là tác giả của {p}?",
        "Bài {p} có danh sách tác giả nào?",
    ),
    QueryAction.TOPIC_PAPERS: (
        "Các bài đã gắn nhãn chủ đề {t} là gì?",
        "Corpus có những công trình nào thuộc chủ đề {t}?",
    ),
    QueryAction.PAPER_VENUE: (
        "Bài {p} xuất hiện ở venue nào?",
        "Venue của công trình {p} là gì?",
    ),
    QueryAction.PAPER_CITATIONS: (
        "Bài {p} được trích dẫn bởi bài nào trong corpus?",
        "Những citation nội bộ corpus liên quan đến {p} là gì?",
    ),
    QueryAction.ORG_COLLABORATIONS: (
        "{i} hợp tác với tổ chức nào trong corpus?",
        "Các cơ quan đồng xuất hiện trên bài với {i} gồm những nơi nào?",
    ),
    QueryAction.AUTHOR_PATH: (
        "Đường đồng tác giả giữa {a} và {b} là gì?",
        "Hãy tìm đường nối {a} với {b} qua tối đa bốn cạnh đồng tác giả.",
    ),
    QueryAction.NETWORK_TOP: (
        "Top tác giả theo số đồng tác giả riêng biệt là ai?",
        "Xếp hạng tác giả có nhiều cộng tác viên khác nhau nhất trong graph.",
    ),
    QueryAction.PAPER_METHODS: (
        "Bài {p} sử dụng phương pháp nào?",
        "Các Method được trích xuất từ abstract của {p} là gì?",
    ),
    QueryAction.METHOD_PAPERS: (
        "Những bài nào sử dụng phương pháp {m}?",
        "Corpus có công trình nào nhắc việc dùng {m}?",
    ),
    QueryAction.PAPER_DATASETS: (
        "Bài {p} được đánh giá trên bộ dữ liệu nào?",
        "Các Dataset được trích xuất từ abstract của {p} là gì?",
    ),
    QueryAction.DATASET_PAPERS: (
        "Những bài nào được đánh giá trên {d}?",
        "Corpus có công trình nào báo cáo kết quả trên {d}?",
    ),
    QueryAction.PAPER_TASKS: (
        "Bài {p} giải quyết bài toán nào?",
        "Các Task được trích xuất từ abstract của {p} là gì?",
    ),
    QueryAction.TASK_PAPERS: (
        "Những bài nào giải quyết bài toán {k}?",
        "Corpus có công trình nào nhắm tới task {k}?",
    ),
    QueryAction.METHOD_TRENDS: (
        "Phương pháp nào được dùng nhiều nhất trong corpus?",
        "Xếp hạng Method theo số bài báo có bằng chứng trong abstract.",
    ),
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


def _legacy_specs(authors, papers, topics, institutions, methods, datasets, tasks) -> list[Spec]:
    """Canonical templates over the first entities (deterministic plumbing)."""
    if len(authors) < 2 or not all((papers, topics, institutions, methods, datasets, tasks)):
        raise ValueError("graph needs 2 authors and one paper/topic/institution/method/dataset/task")
    author_a, author_b = authors[0], authors[1]
    paper = papers[0]
    topic = topics[0]
    institution = institutions[0]
    method = methods[0]
    dataset = datasets[0]
    task = tasks[0]
    a = {"a": author_a.name}
    ab = {"a": author_a.name, "b": author_b.name}
    p = {"p": paper.name}
    t = {"t": topic.name}
    i = {"i": institution.name}
    m = {"m": method.name}
    d = {"d": dataset.name}
    k = {"k": task.name}
    mention_a = [_author_mention(author_a)]
    mention_ab = [_author_mention(author_a), _author_mention(author_b)]
    mention_paper = [EntityMention(text=paper.name, type="Paper")]
    mention_topic = [EntityMention(text=topic.name, type="Topic")]
    mention_inst = [EntityMention(text=institution.name, type="Institution")]
    mention_method = [EntityMention(text=method.name, type="Method")]
    mention_dataset = [EntityMention(text=dataset.name, type="Dataset")]
    mention_task = [EntityMention(text=task.name, type="Task")]
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
        Spec(QueryAction.PAPER_METHODS, {"paper_id": paper.id}, p, mention_paper),
        Spec(
            QueryAction.METHOD_PAPERS,
            {"method_id": method.id, "year_from": None, "year_to": None},
            m,
            mention_method,
        ),
        Spec(QueryAction.PAPER_DATASETS, {"paper_id": paper.id}, p, mention_paper),
        Spec(
            QueryAction.DATASET_PAPERS,
            {"dataset_id": dataset.id, "year_from": None, "year_to": None},
            d,
            mention_dataset,
        ),
        Spec(QueryAction.PAPER_TASKS, {"paper_id": paper.id}, p, mention_paper),
        Spec(
            QueryAction.TASK_PAPERS,
            {"task_id": task.id, "year_from": None, "year_to": None},
            k,
            mention_task,
        ),
        Spec(QueryAction.METHOD_TRENDS, {"year_from": None, "year_to": None}, {}, []),
    ]


def _pick(items: list, count: int, rng: random.Random) -> list:
    """Return up to `count` distinct items in a reproducible shuffled order."""
    if count <= 0 or not items:
        return []
    shuffled = list(items)
    rng.shuffle(shuffled)
    return shuffled[:count]


def _unique_name_entities(items: list) -> list:
    """Keep only entities whose normalized display name maps to one graph ID.

    Generated questions mention display names, not hidden IDs. A duplicated name would therefore
    produce an ambiguous runtime question while the generated label silently chose one ID.
    Excluding those entities keeps the candidate contract honest; ambiguity cases are generated
    separately and carry an explicit ``ambiguous`` expected status.
    """
    name_counts = Counter(item.name.casefold().strip() for item in items)
    return [item for item in items if name_counts[item.name.casefold().strip()] == 1]


def _sampled_specs(
    authors, papers, topics, institutions, methods, datasets, tasks, per_action: int, rng: random.Random
) -> list[Spec]:
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
        specs.append(Spec(QueryAction.PAPER_METHODS, {"paper_id": paper.id}, values, mention))
        specs.append(Spec(QueryAction.PAPER_DATASETS, {"paper_id": paper.id}, values, mention))
        specs.append(Spec(QueryAction.PAPER_TASKS, {"paper_id": paper.id}, values, mention))

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

    for method in _pick(methods, per_action, rng):
        specs.append(
            Spec(
                QueryAction.METHOD_PAPERS,
                {"method_id": method.id, "year_from": None, "year_to": None},
                {"m": method.name},
                [EntityMention(text=method.name, type="Method")],
            )
        )

    for dataset in _pick(datasets, per_action, rng):
        specs.append(
            Spec(
                QueryAction.DATASET_PAPERS,
                {"dataset_id": dataset.id, "year_from": None, "year_to": None},
                {"d": dataset.name},
                [EntityMention(text=dataset.name, type="Dataset")],
            )
        )

    for task in _pick(tasks, per_action, rng):
        specs.append(
            Spec(
                QueryAction.TASK_PAPERS,
                {"task_id": task.id, "year_from": None, "year_to": None},
                {"k": task.name},
                [EntityMention(text=task.name, type="Task")],
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
    specs.append(Spec(QueryAction.METHOD_TRENDS, {"year_from": None, "year_to": None}, {}, []))

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
    snapshot_version: str | None = None,
) -> list[QuestionCase]:
    if provider == "neo4j" and not execute:
        raise ValueError("Neo4j generation is read-only but still requires explicit --execute")
    repository = await build_repository(provider)
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
        methods = by_label.get("Method", [])
        datasets = by_label.get("Dataset", [])
        tasks = by_label.get("Task", [])

        if per_action > 0:
            authors = _unique_name_entities(authors)
            papers = _unique_name_entities(papers)
            topics = _unique_name_entities(topics)
            institutions = _unique_name_entities(institutions)
            methods = _unique_name_entities(methods)
            datasets = _unique_name_entities(datasets)
            tasks = _unique_name_entities(tasks)
            specs = _sampled_specs(
                authors,
                papers,
                topics,
                institutions,
                methods,
                datasets,
                tasks,
                per_action,
                rng,
            )
        else:
            specs = _legacy_specs(authors, papers, topics, institutions, methods, datasets, tasks)

        cases: list[QuestionCase] = []
        for spec in specs:
            if len(cases) >= limit:
                break
            step = QueryStep(action=spec.action, params=spec.params, expected_fields=[], limit=100)
            result = await repository.execute(step)
            facts = normalizer.normalize(result.records)
            fact_dicts = [fact.model_dump(mode="json") for fact in facts]
            citations = build_citations(facts)
            answer = _answer_from_facts(facts)
            if result.truncated:
                status = "partial"
            elif facts:
                status = "answered"
            else:
                status = "not_found"
            entity_ids = [str(value) for key, value in spec.params.items() if key.endswith("_id")]
            templates = (
                QUESTION_VARIANTS[spec.action] if per_action > 0 else (QUESTION_TEMPLATES[spec.action],)
            )

            for variant_index, template in enumerate(templates, start=1):
                if len(cases) >= limit:
                    break
                case_index = len(cases) + 1
                question = template.format(**spec.values)
                cases.append(
                    QuestionCase(
                        case_id=f"generated-{seed}-{case_index:05d}",
                        question=question,
                        expected_route="graph_qa",
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
                        snapshot_version=(
                            snapshot_version
                            or ("synthetic-v1" if provider == "fake" else "live-readonly-unversioned")
                        ),
                        template_id=f"{spec.action.value}.v{variant_index}",
                        group_id="|".join(sorted(entity_ids)) or spec.action.value,
                        seed=seed,
                        review_status=ReviewStatus.NEEDS_REVIEW,
                        provenance={
                            "provider": provider,
                            "records": len(result.records),
                            "truncated": result.truncated,
                            "query_fingerprint": step.fingerprint,
                            "validation_level": "candidate_generation_query",
                        },
                    )
                )
        return cases
    finally:
        await repository.close()


async def build_repository(provider: str):
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
        settings.neo4j_enrichment_scope_id,
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
        help="entities to sample per template (0 = canonical templates only)",
    )
    parser.add_argument(
        "--snapshot-version",
        help="immutable graph snapshot identifier (for example processed manifest sha256)",
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    cases = asyncio.run(
        generate(
            args.provider,
            args.seed,
            args.limit,
            args.execute,
            args.per_action,
            args.snapshot_version,
        )
    )
    count = write_models(args.out, cases)
    print(f"wrote {count} candidate cases to {args.out} (not gold; human review required)")


if __name__ == "__main__":
    main()
