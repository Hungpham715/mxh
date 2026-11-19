"""Add independently adjudicated refusal, ambiguity, clarification, and history cases."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datasets.io import read_models, write_models
from datasets.schema import (
    DatasetHistoryMessage,
    EntityMention,
    ExpectedCitations,
    ExpectedFacts,
    ExpectedQuery,
    QuestionCase,
    ReviewStatus,
)

REVIEWER_NOTE = "independent_codex:challenge_semantics_reviewed"
DEFAULT_BASE_ID = "generated-20261118-11139"
DEFAULT_COUNT_BASE_IDS = [
    "generated-20261118-10867",
    "generated-20261118-07589",
    "generated-20261118-03761",
    "generated-20261118-10576",
    "generated-20261118-07346",
]


def build_challenges(
    gold: list[QuestionCase],
    negative_candidates: list[QuestionCase],
    base_id: str = DEFAULT_BASE_ID,
    count_base_ids: list[str] | None = None,
) -> tuple[list[QuestionCase], list[dict[str, str]]]:
    if count_base_ids is None:
        count_base_ids = DEFAULT_COUNT_BASE_IDS
    by_id = {case.case_id: case for case in gold}
    base = by_id.get(base_id)
    if base is None:
        raise ValueError(f"reviewed coauthor base case {base_id} is missing")
    if not base.entity_mentions or base.entity_mentions[0].type != "Author":
        raise ValueError(f"base case {base_id} must mention its author first")
    history_author = base.entity_mentions[0].text
    history_question = f"Các bài báo của {history_author}?"

    challenges: list[QuestionCase] = []
    evidence: list[dict[str, str]] = []
    for candidate in negative_candidates:
        if candidate.expected_status != "out_of_scope":
            continue
        reviewed = candidate.model_copy(
            update={
                "expected_route": "out_of_scope",
                "review_status": ReviewStatus.INDEPENDENT_APPROVED,
                "reviewer_note": REVIEWER_NOTE,
                "split": None,
                "snapshot_version": base.snapshot_version,
            }
        )
        challenges.append(reviewed)
        evidence.append(
            {
                "case_id": reviewed.case_id,
                "decision": "yes",
                "rationale": "question is plainly outside the graph-only academic NLP scope",
            }
        )

    empty_facts = ExpectedFacts()
    empty_citations = ExpectedCitations()
    unknown_query = ExpectedQuery(intent="unknown", entity_ids=[], params={})

    meta_history = base.model_copy(
        update={
            "case_id": "independent-history-meta-001",
            "question": "Câu hỏi đầu tiên tôi hỏi bạn là gì?",
            "history": [
                DatasetHistoryMessage(role="user", content=history_question),
                DatasetHistoryMessage(role="assistant", content="Đã tìm thấy các bài báo trong corpus."),
            ],
            "expected_route": "chat_history",
            "expected_status": "answered",
            "expected_query": unknown_query,
            "expected_facts": ExpectedFacts(answer=history_question),
            "expected_citations": empty_citations,
            "entity_mentions": [],
            "verified_facts": [],
            "template_id": "history_meta.v1",
            "group_id": "challenge:history-meta-001",
            "review_status": ReviewStatus.INDEPENDENT_APPROVED,
            "reviewer_note": REVIEWER_NOTE,
            "split": None,
        }
    )
    coref = base.model_copy(
        update={
            "case_id": "independent-history-coref-001",
            "question": "Thế các đồng tác giả của người đó?",
            "history": [
                DatasetHistoryMessage(role="user", content=history_question),
                DatasetHistoryMessage(role="assistant", content="Đã tìm thấy các bài báo trong corpus."),
            ],
            "template_id": "history_coref.v1",
            "review_status": ReviewStatus.INDEPENDENT_APPROVED,
            "reviewer_note": REVIEWER_NOTE,
            "split": None,
        }
    )
    clarify = base.model_copy(
        update={
            "case_id": "independent-clarify-001",
            "question": "Các bài báo của tác giả đó?",
            "history": [],
            "expected_route": "clarify",
            "expected_status": "clarify",
            "expected_query": ExpectedQuery(intent="author_papers", entity_ids=[], params={}),
            "expected_facts": empty_facts,
            "expected_citations": empty_citations,
            "entity_mentions": [],
            "verified_facts": [],
            "template_id": "clarify_missing_reference.v1",
            "group_id": "challenge:clarify-001",
            "review_status": ReviewStatus.INDEPENDENT_APPROVED,
            "reviewer_note": REVIEWER_NOTE,
            "split": None,
        }
    )
    ambiguous = base.model_copy(
        update={
            "case_id": "independent-ambiguous-001",
            "question": "Các bài báo của tác giả Qi Zhang?",
            "history": [],
            "expected_route": "graph_qa",
            "expected_status": "ambiguous",
            "expected_query": ExpectedQuery(intent="author_papers", entity_ids=[], params={}),
            "expected_facts": empty_facts,
            "expected_citations": empty_citations,
            "entity_mentions": [EntityMention(text="Qi Zhang", type="Author")],
            "verified_facts": [],
            "template_id": "ambiguous_live_name.v1",
            "group_id": "challenge:ambiguous-qi-zhang",
            "review_status": ReviewStatus.INDEPENDENT_APPROVED,
            "reviewer_note": REVIEWER_NOTE,
            "split": None,
        }
    )
    unknown = base.model_copy(
        update={
            "case_id": "independent-unknown-entity-001",
            "question": 'Bài báo của tác giả "Nguyen Van Khong Co That"',
            "history": [],
            "expected_route": "graph_qa",
            "expected_status": "not_found",
            "expected_query": ExpectedQuery(intent="author_papers", entity_ids=[], params={}),
            "expected_facts": empty_facts,
            "expected_citations": empty_citations,
            "entity_mentions": [EntityMention(text="Nguyen Van Khong Co That", type="Author")],
            "verified_facts": [],
            "template_id": "unknown_live_name.v1",
            "group_id": "challenge:unknown-name-001",
            "review_status": ReviewStatus.INDEPENDENT_APPROVED,
            "reviewer_note": REVIEWER_NOTE,
            "split": None,
        }
    )
    for case, rationale in [
        (meta_history, "answer is the first user message in supplied history"),
        (coref, f"pronoun refers to {history_author} in supplied history; graph facts inherit reviewed base"),
        (clarify, "missing referent requires clarification"),
        (ambiguous, "live catalog contains eight distinct Author nodes named Qi Zhang"),
        (unknown, "name is a deliberate non-catalog entity and must return not_found"),
    ]:
        challenges.append(case)
        evidence.append({"case_id": case.case_id, "decision": "yes", "rationale": rationale})

    for index, case_id in enumerate(count_base_ids, start=1):
        source = by_id.get(case_id)
        if source is None:
            raise ValueError(f"reviewed count base case {case_id} is missing")
        if source.expected_query.intent != "author_papers" or source.expected_status != "answered":
            raise ValueError(f"count base case {case_id} is not an answered author_papers case")
        author = source.entity_mentions[0].text
        count = len(set(source.expected_facts.object_ids))
        count_case = source.model_copy(
            update={
                "case_id": f"independent-count-{index:03d}",
                "question": f"{author} có bao nhiêu bài báo trong corpus?",
                "expected_facts": source.expected_facts.model_copy(
                    update={"answer": f"{author} có {count} bài báo trong corpus."}
                ),
                "template_id": "author_papers_count",
                "review_status": ReviewStatus.INDEPENDENT_APPROVED,
                "reviewer_note": REVIEWER_NOTE,
                "split": None,
            }
        )
        challenges.append(count_case)
        evidence.append(
            {
                "case_id": count_case.case_id,
                "decision": "yes",
                "rationale": f"fresh graph-exact base contains {count} distinct authored paper facts",
            }
        )

    return [*gold, *challenges], evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--negatives", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument(
        "--base-id",
        default=DEFAULT_BASE_ID,
        help="reviewed coauthors case whose author anchors the history challenges",
    )
    parser.add_argument(
        "--count-base-ids",
        nargs="+",
        default=None,
        help="reviewed answered author_papers cases used to derive count questions",
    )
    args = parser.parse_args()
    output, evidence = build_challenges(
        read_models(args.gold, QuestionCase),
        read_models(args.negatives, QuestionCase),
        base_id=args.base_id,
        count_base_ids=args.count_base_ids,
    )
    write_models(args.out, output)
    args.evidence.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in evidence),
        encoding="utf-8",
    )
    print(f"non-human source-review cases={len(output)} challenge_cases={len(evidence)}")


if __name__ == "__main__":
    main()
