"""Compare B0/B1 and optional B2 summaries from the same reviewed test set."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def compare(b0_path: Path, b1_path: Path, b2_path: Path | None) -> dict:
    b0 = json.loads(b0_path.read_text(encoding="utf-8"))
    b1 = json.loads(b1_path.read_text(encoding="utf-8"))
    if b0.get("synthetic_smoke_only") or b1.get("synthetic_smoke_only"):
        raise ValueError("B0/B1 comparison requires reviewed held-out evaluation, not synthetic smoke")
    if b0["dataset_sha256"] != b1["dataset_sha256"]:
        raise ValueError("B0 and B1 must use the exact same held-out dataset")
    result = {"B0_base_one_step": b0, "B1_base_iterative": b1, "B2_sft_iterative": "not_run"}
    if b2_path is not None:
        b2 = json.loads(b2_path.read_text(encoding="utf-8"))
        if b2["dataset_sha256"] != b0["dataset_sha256"]:
            raise ValueError("B2 must use the same held-out dataset")
        result["B2_sft_iterative"] = b2
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--b0", type=Path, required=True)
    parser.add_argument("--b1", type=Path, required=True)
    parser.add_argument("--b2", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.b0, args.b1, args.b2)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "comparison.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with (args.out / "comparison.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["baseline", "status", "query_template_accuracy", "answer_token_f1"])
        for baseline, data in result.items():
            if data == "not_run":
                writer.writerow([baseline, "not_run", "", ""])
            else:
                writer.writerow(
                    [
                        baseline,
                        "run",
                        data["metrics"]["query_template_accuracy"],
                        data["metrics"]["answer_token_f1"],
                    ]
                )
    print(f"wrote comparison to {args.out}; B2={result['B2_sft_iterative'] != 'not_run'}")


if __name__ == "__main__":
    main()
