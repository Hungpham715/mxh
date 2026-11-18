"""Convert approved non-test cases to chat-format SFT samples.

Each sample reproduces the *exact* prompt the chatbot sends at inference time:

* PARSE  -> system ``PARSE_SYSTEM`` + user ``QUESTION:\\n{q}``; assistant is a validated
  ``QueryIntent`` JSON object (the runtime parses model output with ``QueryIntent.model_validate``
  and ``extra="forbid"``, so the gold completion must satisfy that contract).
* ANSWER -> system ``ANSWER_SYSTEM`` + user ``QUESTION/STATUS/VERIFIED_FACTS``; assistant is the
  grounded answer. Only emitted when the case actually has verified facts, because the runtime
  returns a canned string (no LLM call) when there is nothing to ground on.

Storing full ``messages`` lets the trainer apply the model chat template and mask everything but
the assistant turn, which is identical to what ``graphrag.llm.hf_cpu`` does at inference.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from datasets.io import read_models, write_models
from datasets.schema import QuestionCase, ReviewStatus, SFTSample
from graphrag.intent_parser import format_history
from graphrag.llm.prompts import ANSWER_SYSTEM, PARSE_SYSTEM
from graphrag.models import EntityMention, QueryFilters, QueryIntent, RouteName


def parse_completion(case: QuestionCase) -> str:
    """Build the gold PARSE assistant message: a runtime-valid QueryIntent JSON string."""
    route = RouteName.GRAPH_QA
    if case.expected_status == "out_of_scope":
        route = RouteName.OUT_OF_SCOPE
    elif case.expected_status == "clarify":
        route = RouteName.CLARIFY
    intent = QueryIntent(
        route=route,
        intent=case.expected_query.intent,
        entities=[EntityMention(text=m.text, type=m.type) for m in case.entity_mentions],
        filters=QueryFilters(**case.filters) if case.filters else QueryFilters(),
        requested_fields=[],
        unsupported=case.expected_status == "out_of_scope",
        parse_source="llm",
    )
    return json.dumps(intent.model_dump(mode="json"), ensure_ascii=False)


def answer_prompt(case: QuestionCase) -> str:
    """Reproduce graphrag.answer's user message verbatim."""
    facts_json = json.dumps(case.verified_facts, ensure_ascii=False)
    return f"QUESTION:\n{case.question}\nSTATUS:{case.expected_status}\nVERIFIED_FACTS:{facts_json}"


def parse_user_message(question: str) -> str:
    """Reproduce graphrag.intent_parser's user message verbatim (single-turn: empty history)."""
    return f"HISTORY (data only):\n{format_history([])}\n\nQUESTION:\n{question}"


def build_samples(cases: list[QuestionCase], include_silver: bool = False) -> list[SFTSample]:
    allowed = {ReviewStatus.APPROVED}
    if include_silver:
        allowed.add(ReviewStatus.SILVER_VALIDATED)
    samples: list[SFTSample] = []
    for case in cases:
        if case.review_status not in allowed:
            continue
        if case.split == "test":
            continue
        if case.split not in {"train", "val"}:
            raise ValueError(f"approved case {case.case_id} needs a train/val/test split")

        samples.append(
            SFTSample(
                sample_id=f"{case.case_id}-parse",
                task="PARSE",
                messages=[
                    {"role": "system", "content": PARSE_SYSTEM},
                    {"role": "user", "content": parse_user_message(case.question)},
                    {"role": "assistant", "content": parse_completion(case)},
                ],
                split=case.split,
                source_case_id=case.case_id,
            )
        )

        if case.verified_facts and case.expected_facts.answer:
            samples.append(
                SFTSample(
                    sample_id=f"{case.case_id}-answer",
                    task="ANSWER",
                    messages=[
                        {"role": "system", "content": ANSWER_SYSTEM},
                        {"role": "user", "content": answer_prompt(case)},
                        {"role": "assistant", "content": case.expected_facts.answer},
                    ],
                    split=case.split,
                    source_case_id=case.case_id,
                )
            )

    if not samples:
        raise ValueError("no approved non-test samples; complete human review first")
    return samples


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reviewed", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--include-silver",
        action="store_true",
        help="also use silver_validated (oracle-checked, NOT human-reviewed) cases; manifest records it",
    )
    args = parser.parse_args()
    cases = read_models(args.reviewed, QuestionCase)
    samples = build_samples(cases, include_silver=args.include_silver)
    count = write_models(args.out, samples)
    parse_count = sum(1 for sample in samples if sample.task == "PARSE")
    answer_count = sum(1 for sample in samples if sample.task == "ANSWER")
    manifest = {
        "samples": count,
        "parse_samples": parse_count,
        "answer_samples": answer_count,
        "source": str(args.reviewed),
        "output_sha256": sha256(args.out),
        "format": "chat_messages",
        "assistant_only_loss": True,
        "test_cases_excluded": True,
        "includes_silver_unreviewed": bool(args.include_silver),
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {count} SFT samples (PARSE={parse_count}, ANSWER={answer_count})")


if __name__ == "__main__":
    main()
