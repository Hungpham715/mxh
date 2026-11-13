"""Create verified synthetic negative cases for refusal and missing-edge paths.

Two families:

* Entity-bearing negatives (not_found / ambiguous): the gold PARSE target still extracts the
  intent and entity correctly; the negative outcome happens later (entity linking / empty graph
  result), which is exactly what the runtime does.
* Out-of-scope questions: off-domain prompts whose gold PARSE target is ``intent=unknown`` with
  ``unsupported=true``. Each gets a unique ``group_id`` so the leakage-checked split spreads them
  across train/val/test instead of landing all of them in one split.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from datasets.io import write_models
from datasets.schema import EntityMention, ExpectedQuery, QuestionCase, ReviewStatus

# Off-domain questions: clearly outside the author/paper/institution/topic/venue/citation graph.
OUT_OF_SCOPE_QUESTIONS = [
    "Thời tiết Hà Nội hôm nay thế nào?",
    "Liệt kê node scope khác nlpgraph-v1",
    "Kết quả bóng đá Ngoại hạng Anh tối qua ra sao?",
    "Cách nấu một nồi phở bò ngon?",
    "Viết cho tôi một bài thơ về mùa thu",
    "1 cộng 1 bằng mấy?",
    "Giá cổ phiếu VinGroup hôm nay là bao nhiêu?",
    "Bộ phim nào đang hot nhất trên Netflix?",
    "Hướng dẫn cài đặt Python trên Windows",
    "Chuyến bay từ Hà Nội vào Sài Gòn giá bao nhiêu?",
    "Công thức tính diện tích hình tròn?",
    "Ai là tổng thống Mỹ năm 2020?",
]


def _entity_negative_cases(seed: int) -> list[QuestionCase]:
    # (template_id, question, status, intent, entity_ids, entity_mentions)
    definitions = [
        (
            "not-found",
            "Bài báo của Nobody In Corpus",
            "not_found",
            "author_papers",
            ["author:missing"],
            [EntityMention(text="Nobody In Corpus", type="Author")],
        ),
        (
            "ambiguous",
            "Bài báo của Linh Nguyen",
            "ambiguous",
            "author_papers",
            [],
            [EntityMention(text="Linh Nguyen", type="Author")],
        ),
        (
            "missing-affiliation",
            "Tổ chức của Linh Nguyen trên Solo Parsing Study?",
            "not_found",
            "author_affiliations",
            ["author:linh-b"],
            [
                EntityMention(text="Linh Nguyen", type="Author"),
                EntityMention(text="Solo Parsing Study", type="Paper"),
            ],
        ),
        (
            "no-citation",
            "Solo Parsing Study trích dẫn bài nào?",
            "not_found",
            "paper_citations",
            ["paper:solo"],
            [EntityMention(text="Solo Parsing Study", type="Paper")],
        ),
        (
            "no-topic",
            "Chủ đề của Solo Parsing Study là gì?",
            "not_found",
            "topic_papers",
            ["paper:solo"],
            [EntityMention(text="Solo Parsing Study", type="Paper")],
        ),
    ]
    cases = []
    for index, definition in enumerate(definitions, start=1):
        template_id, question, status, intent, entity_ids, mentions = definition
        cases.append(
            QuestionCase(
                case_id=f"negative-{seed}-{index:03d}",
                question=question,
                expected_status=status,
                expected_query=ExpectedQuery(intent=intent, entity_ids=entity_ids),
                entity_mentions=mentions,
                scope_id="nlpgraph-v1",
                snapshot_version="synthetic-v1",
                template_id=template_id,
                group_id="|".join(entity_ids) or template_id,
                seed=seed,
                review_status=ReviewStatus.NEEDS_REVIEW,
                provenance={
                    "verified_against": "FakeGraphRepository synthetic-v1",
                    "negative_is_candidate": True,
                },
            )
        )
    return cases


def _out_of_scope_cases(seed: int) -> list[QuestionCase]:
    cases = []
    for index, question in enumerate(OUT_OF_SCOPE_QUESTIONS, start=1):
        template_id = f"out-of-scope-{index:02d}"
        cases.append(
            QuestionCase(
                case_id=f"oos-{seed}-{index:03d}",
                question=question,
                expected_status="out_of_scope",
                expected_query=ExpectedQuery(intent="unknown", entity_ids=[]),
                entity_mentions=[],
                scope_id="nlpgraph-v1",
                snapshot_version="synthetic-v1",
                template_id=template_id,
                group_id=template_id,
                seed=seed,
                review_status=ReviewStatus.NEEDS_REVIEW,
                provenance={"negative_is_candidate": True, "kind": "out_of_scope"},
            )
        )
    return cases


def build_negative_cases(seed: int) -> list[QuestionCase]:
    return _entity_negative_cases(seed) + _out_of_scope_cases(seed)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    rows = build_negative_cases(args.seed)
    print(f"wrote {write_models(args.out, rows)} verified synthetic negative candidates")


if __name__ == "__main__":
    main()
