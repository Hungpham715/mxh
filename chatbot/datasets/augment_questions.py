"""Rule-based paraphrase candidates; all outputs remain needs_review."""

from __future__ import annotations

import argparse
from pathlib import Path

from datasets.io import read_models, write_models
from datasets.schema import QuestionCase, ReviewStatus

REPLACEMENTS = [
    ("có những", "gồm các"),
    ("là ai", "bao gồm những ai"),
    ("là gì", "gồm những gì"),
    ("trong corpus", "theo corpus"),
]


def augment(cases: list[QuestionCase]) -> list[QuestionCase]:
    output: list[QuestionCase] = []
    for case in cases:
        for index, (old, new) in enumerate(REPLACEMENTS, start=1):
            if old not in case.question:
                continue
            question = case.question.replace(old, new)
            output.append(
                case.model_copy(
                    update={
                        "case_id": f"{case.case_id}-aug-{index}",
                        "question": question,
                        "review_status": ReviewStatus.NEEDS_REVIEW,
                        "template_id": f"{case.template_id}.rule_aug_{index}",
                        "provenance": {
                            **case.provenance,
                            "augmentation": "rule_based",
                            "source_case_id": case.case_id,
                        },
                    }
                )
            )
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--provider", choices=["rules", "ollama"], default="rules")
    args = parser.parse_args()
    if args.provider != "rules":
        raise SystemExit("Ollama augmentation is opt-in and not enabled in v1; use --provider rules")
    cases = read_models(args.input, QuestionCase)
    print(f"wrote {write_models(args.out, augment(cases))} non-gold paraphrase candidates")


if __name__ == "__main__":
    main()
