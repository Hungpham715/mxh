"""Programmatic source-consistency gate for generated candidates.

The module re-runs every catalog query and requires exact facts, citations, status, and query
fingerprint. Passing rows are source-validated silver only: they are consistent with the graph
snapshot, but they are not human gold and do not prove the graph itself is semantically true.

Output is a CSV in the same column format as ``export_review`` so ``import_review`` can consume
it unchanged (import_review preserves the runtime-aligned fields from the source case).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from pathlib import Path

from datasets.export_review import FIELDS
from datasets.generate_from_graph import build_repository
from datasets.io import read_models
from datasets.schema import QuestionCase
from graphrag.evidence import EvidenceNormalizer, build_citations
from graphrag.models import QueryAction, QueryStep

# Minimum entity mentions of the required type for each intent's gold PARSE target.
REQUIRED_MENTIONS: dict[str, tuple[str, int]] = {
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
    "network_top": ("", 0),
    "unknown": ("", 0),
}

VALID_INTENTS = set(REQUIRED_MENTIONS)


def gate(case: QuestionCase) -> tuple[bool, str]:
    """Return (label_valid, reason). Strict structural checks only; no graph re-query."""
    if not case.question.strip():
        return False, "empty_question"

    intent = case.expected_query.intent
    if intent not in VALID_INTENTS:
        return False, f"unknown_intent:{intent}"

    required_type, required_count = REQUIRED_MENTIONS[intent]
    if required_count == 0:
        if case.entity_mentions:
            return False, "unexpected_mentions_for_intent"
    else:
        matching = [m for m in case.entity_mentions if m.type == required_type and m.text.strip()]
        if len(matching) < required_count:
            return False, f"needs_{required_count}_{required_type}_mentions"

    # Answered/partial cases must be groundable: facts present and a non-empty gold answer.
    if case.expected_status in {"answered", "partial"}:
        if not case.verified_facts:
            return False, "answered_without_verified_facts"
        if not case.expected_facts.answer.strip():
            return False, "answered_without_answer"

    # Negative cases (not_found/out_of_scope/ambiguous) are kept for refusal training; they
    # need a valid intent and, except out_of_scope, correct entity mentions (checked above).
    return True, "passed"


def _review_row(case: QuestionCase, valid: bool, reason: str) -> dict[str, str]:
    return {
        "case_id": case.case_id,
        "question": case.question,
        "expected_answer": case.expected_facts.answer,
        "expected_entities": json.dumps(case.expected_query.entity_ids, ensure_ascii=False),
        "expected_paper_ids": json.dumps(case.expected_citations.paper_ids, ensure_ascii=False),
        "source_urls": json.dumps(case.expected_citations.source_urls, ensure_ascii=False),
        "label_valid": "yes" if valid else "no",
        "reviewer_note": f"silver_auto:{reason}",
    }


def label_cases(cases: list[QuestionCase]) -> tuple[list[dict[str, str]], dict[str, int]]:
    """Run structural checks only.

    This helper remains useful for unit tests and diagnostics, but its output alone is not
    source-validated silver. The CLI uses :func:`validate_cases_against_graph` instead.
    """
    rows: list[dict[str, str]] = []
    stats: dict[str, int] = {"yes": 0, "no": 0}
    for case in cases:
        valid, reason = gate(case)
        label = "yes" if valid else "no"
        stats[label] += 1
        rows.append(_review_row(case, valid, f"structural_only:{reason}"))
    return rows, stats


async def validate_cases_against_graph(
    cases: list[QuestionCase], provider: str, execute: bool
) -> tuple[list[dict[str, str]], dict[str, int]]:
    """Re-run every candidate query and require an exact graph-fact/citation match.

    This is an independent execution pass over the immutable snapshot, not human review and not
    semantic proof that the graph itself is true. Passing rows may be imported only as
    ``silver_approved``.
    """
    if provider == "neo4j" and not execute:
        raise ValueError("Neo4j silver validation is read-only but requires explicit --execute")

    repository = await build_repository(provider)
    normalizer = EvidenceNormalizer()
    rows: list[dict[str, str]] = []
    stats: dict[str, int] = {"yes": 0, "no": 0}
    try:
        for case in cases:
            structurally_valid, reason = gate(case)
            if not structurally_valid:
                stats["no"] += 1
                rows.append(_review_row(case, False, f"structural:{reason}"))
                continue

            try:
                action = QueryAction(case.expected_query.intent)
                step = QueryStep(
                    action=action,
                    params=case.expected_query.params,
                    expected_fields=[],
                    limit=100,
                )
                result = await repository.execute(step)
                facts = normalizer.normalize(result.records)
                citations = build_citations(facts)

                actual_fact_ids = {fact.fact_id for fact in facts}
                expected_fact_ids = {
                    str(fact.get("fact_id"))
                    for fact in case.verified_facts
                    if fact.get("fact_id") is not None
                }
                actual_paper_ids = {citation.paper_id for citation in citations}
                expected_paper_ids = set(case.expected_citations.paper_ids)
                actual_urls = {citation.url for citation in citations}
                expected_urls = set(case.expected_citations.source_urls)
                actual_status = "partial" if result.truncated else ("answered" if facts else "not_found")

                checks = {
                    "status": actual_status == case.expected_status,
                    "facts": actual_fact_ids == expected_fact_ids,
                    "paper_ids": actual_paper_ids == expected_paper_ids,
                    "source_urls": actual_urls == expected_urls,
                    "fingerprint": step.fingerprint == str(case.provenance.get("query_fingerprint", "")),
                }
                failed = [name for name, passed in checks.items() if not passed]
                valid = not failed
                reason = "graph_requery_exact_match" if valid else "mismatch:" + ",".join(failed)
            except (ValueError, TypeError, KeyError) as error:
                valid = False
                reason = f"validation_error:{type(error).__name__}"

            label = "yes" if valid else "no"
            stats[label] += 1
            rows.append(_review_row(case, valid, reason))
    finally:
        await repository.close()
    return rows, stats


def write_review_csv(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--provider", choices=["fake", "neo4j"], required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    cases = read_models(args.input, QuestionCase)
    rows, stats = asyncio.run(validate_cases_against_graph(cases, args.provider, args.execute))
    write_review_csv(rows, args.out)
    print(
        f"source-revalidated {len(cases)} candidates -> {args.out} "
        f"(yes={stats['yes']} no={stats['no']}; silver only, not human gold)"
    )


if __name__ == "__main__":
    main()
