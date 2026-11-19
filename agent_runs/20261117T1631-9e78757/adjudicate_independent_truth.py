#!/usr/bin/env python3
"""Apply explicit PDF-based adjudications to the independent source-review output."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


DECISIONS: dict[str, tuple[str, str, str]] = {
    "AFFILIATED_WITH-11": (
        "incorrect",
        "wrong_org",
        "PDF front matter maps Simon Krek to Jožef Stefan Institute and University of Ljubljana, not Jožef Stefan International Postgraduate School.",
    ),
    "AFFILIATED_WITH-36": (
        "incorrect",
        "wrong_org",
        "PDF front matter maps Seraphina Goldfarb-Tarrant to Cohere; University of Cambridge is absent.",
    ),
    "AFFILIATED_WITH-39": (
        "correct",
        "",
        "PDF front matter explicitly states Wroclaw University of Science and Technology and lists Lukasz Augustyniak.",
    ),
    "CITES-02": (
        "correct",
        "",
        "Source-paper PDF references explicitly contain the target title across lines 731-732.",
    ),
    "CITES-08": (
        "correct",
        "",
        "Source-paper PDF references explicitly contain the target title near line 1015.",
    ),
    "ORG_COAUTHORED_WITH-05": (
        "incorrect",
        "entity_merge_error",
        "MIT CSAIL and MIT BCS are units of the same parent MIT; the edge splits parent and child as two collaborating institutions.",
    ),
    "ORG_COAUTHORED_WITH-07": (
        "correct",
        "",
        "SEA-VL PDF has distinct authors at Institute for Infocomm Research (affiliation 29) and Universitas Islam Indonesia (21).",
    ),
    "ORG_COAUTHORED_WITH-09": (
        "correct",
        "",
        "PDF front matter has distinct authors at Shanghai AI Laboratory and The University of Hong Kong.",
    ),
    "ORG_COAUTHORED_WITH-14": (
        "correct",
        "",
        "LEME PDF has distinct authors at Harvard Medical School (4) and Duke-NUS Medical School (18).",
    ),
    "ORG_COAUTHORED_WITH-19": (
        "correct",
        "",
        "CASIMIR PDF lists multiple distinct authors under an affiliation containing both École Centrale Nantes and LS2N.",
    ),
    "ORG_COAUTHORED_WITH-20": (
        "incorrect",
        "wrong_org",
        "PDF lists Jožef Stefan Institute, not Jožef Stefan International Postgraduate School; University of Amsterdam alone does not support the edge.",
    ),
    "ORG_COAUTHORED_WITH-28": (
        "correct",
        "",
        "SEA-VL PDF has distinct authors at Universitas Islam Indonesia (21) and National University Philippines (16).",
    ),
    "ORG_COAUTHORED_WITH-31": (
        "correct",
        "",
        "CARE PDF maps authors to the Ministry of Education research center (2) and Dalian University of Technology (3).",
    ),
    "ORG_COAUTHORED_WITH-32": (
        "correct",
        "",
        "SEA-VL PDF has distinct authors at UIUC (40) and AI Singapore (58).",
    ),
    "ORG_COAUTHORED_WITH-36": (
        "correct",
        "",
        "SEA-VL PDF has distinct authors at Universitas Pelita Harapan (54) and Srinakharinwirot University (33).",
    ),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    with args.input.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = reader.fieldnames
    if fieldnames is None:
        raise ValueError("review CSV has no header")
    known = {row["sample_id"] for row in rows}
    missing = sorted(set(DECISIONS) - known)
    if missing:
        raise ValueError(f"adjudication IDs missing from input: {missing}")
    reviewed_at = datetime.now(UTC).isoformat()
    evidence: list[dict[str, str]] = []
    for row in rows:
        decision = DECISIONS.get(row["sample_id"])
        if decision is None:
            continue
        label, error_reason, note = decision
        row.update(
            {
                "reviewer": "codex-independent-source-review-v1+manual-adjudication",
                "reviewed_at_utc": reviewed_at,
                "label": label,
                "error_reason": error_reason,
                "note": note,
                "label_origin": "independent_source_review",
            }
        )
        evidence.append(
            {
                "sample_id": row["sample_id"],
                "label": label,
                "error_reason": error_reason,
                "note": note,
                "evidence_urls": row["evidence_urls"],
            }
        )
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    args.evidence.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in evidence),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "rows": len(rows),
                "adjudicated": len(evidence),
                "output_sha256": sha256(args.output),
                "evidence_sha256": sha256(args.evidence),
            }
        )
    )


if __name__ == "__main__":
    main()
