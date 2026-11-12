"""Synthetic FAKE fixture that follows contract v1 exactly (for tests / offline smoke runs only).

All ids use the 'oa:WFIX..'/'oa:AFIX..'/'oa:IFIX..' prefix so they can never be mistaken for real records.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from src.common import sha256_file, write_json, write_jsonl
from src.data.contracts import FILES, SCHEMA_VERSION

FAKE = "https://example.org/fixture/"


def fixture_tables() -> dict[str, list[dict[str, Any]]]:
    P = lambda i, y, title, abstract, src="acl": {  # noqa: E731
        "id": f"oa:WFIX{i}", "title": title, "year": y, "abstract": abstract, "doi": f"10.0000/fix.{i}",
        "acl_id": f"fix-{i}" if src == "acl" else None, "arxiv_id": None if src == "acl" else f"0000.{i:05d}",
        "source_kind": src, "source_url": f"{FAKE}W{i}",
        "venue_id": "venue:acl:fix-main" if src == "acl" else "venue:arxiv:cs.CL", "openalex_id": f"WFIX{i}"}
    papers = [
        P(1, 2023, "Machine Translation with Large Language Models", "We study machine translation quality."),
        P(2, 2024, "Large Language Models for Question Answering", "A question answering benchmark."),
        P(3, 2024, "Dense Retrieval for Open QA", "We improve dense retrieval and question answering."),
        P(4, 2025, "A Study of Morphology", "Morphological analysis of rare languages.", "arxiv"),
        P(5, 2025, "Hallucination in Large Language Models", "We detect hallucination in summarization outputs."),
    ]
    authors = [{"id": f"oa:AFIX{i}", "name": n, "orcid": None, "openalex_id": f"AFIX{i}", "acl_author_id": None,
                "identity_status": "verified"} for i, n in enumerate(["Ann Lee", "Bo Chen", "Cy Diaz", "Di Eko"], 1)]
    authors.append({"id": "src:oa:WFIX4#1", "name": "Ann Lee", "orcid": None, "openalex_id": None,
                    "acl_author_id": None, "identity_status": "source_only"})  # same name, NOT merged
    auth = {1: ["oa:AFIX1", "oa:AFIX2"], 2: ["oa:AFIX1", "oa:AFIX2", "oa:AFIX3"], 3: ["oa:AFIX3", "oa:AFIX1"],
            4: ["src:oa:WFIX4#1"], 5: ["oa:AFIX4", "oa:AFIX1"]}
    pa = []
    for i, al in auth.items():
        for pos, a in enumerate(al, 1):
            pa.append({"paper_id": f"oa:WFIX{i}", "author_id": a, "position": pos,
                       "author_position": "first" if pos == 1 else ("last" if pos == len(al) else "middle"),
                       "source_url": f"{FAKE}W{i}"})
    insts = [{"id": f"oa:IFIX{i}", "name": n, "ror": None, "country_code": c, "source_url": f"{FAKE}I{i}"}
             for i, n, c in [(1, "Example University", "US"), (2, "Sample Institute", "DE")]]
    years = {p["id"]: p["year"] for p in papers}
    aff_spec = [(1, "oa:AFIX1", 1), (1, "oa:AFIX2", 2), (2, "oa:AFIX1", 1), (2, "oa:AFIX3", 2), (3, "oa:AFIX3", 2),
                (3, "oa:AFIX1", 1)]
    affs = [{"paper_id": f"oa:WFIX{p}", "author_id": a, "institution_id": f"oa:IFIX{i}", "year": years[f"oa:WFIX{p}"],
             "raw_affiliation": None, "source_url": f"{FAKE}W{p}"} for p, a, i in aff_spec]
    venues = [{"id": "venue:acl:fix-main", "name": "Fixture Conference", "kind": "conference", "year": None,
               "source_url": f"{FAKE}venue"},
              {"id": "venue:arxiv:cs.CL", "name": "arXiv cs.CL (preprint)", "kind": "preprint_server", "year": None,
               "source_url": "https://arxiv.org/list/cs.CL/"}]
    cites = [{"citing_paper_id": "oa:WFIX2", "cited_paper_id": "oa:WFIX1", "source_url": f"{FAKE}W2"},
             {"citing_paper_id": "oa:WFIX3", "cited_paper_id": "oa:WFIX2", "source_url": f"{FAKE}W3"}]
    T = lambda p, t, span: {"paper_id": f"oa:WFIX{p}", "topic_id": t, "rule_id": "fixture", "evidence_span": span,  # noqa: E731
                            "confidence_band": "rule_high"}
    topics = [T(1, "mt", "Machine Translation"), T(1, "llm", "Large Language Models"),
              T(2, "llm", "Large Language Models"), T(2, "qa", "Question Answering"),
              T(3, "retrieval", "Dense Retrieval"), T(3, "qa", "question answering"),
              T(5, "safety_eval", "Hallucination"), T(5, "llm", "Large Language Models")]
    return {"papers.jsonl": papers, "authors.jsonl": authors, "institutions.jsonl": insts, "venues.jsonl": venues,
            "paper_authors.jsonl": pa, "affiliations.jsonl": affs, "citations.jsonl": cites,
            "paper_topics.jsonl": topics}


def write_dataset(out: Path, tables: dict[str, list[dict[str, Any]]], scope_id: str = "fixture") -> None:
    out.mkdir(parents=True, exist_ok=True)
    checks, counts = {}, {}
    for f in FILES:
        counts[f] = write_jsonl(out / f, tables[f])
        checks[f] = sha256_file(out / f)
    write_json(out / "manifest.json", {
        "schema_version": SCHEMA_VERSION, "scope_id": scope_id,
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_versions": {"fixture": "synthetic, not real publications"}, "input_counts": {},
        "output_counts": counts, "unmatched_openalex_count": 0, "checksums": checks})


if __name__ == "__main__":
    from src.common import FIXTURES
    write_dataset(FIXTURES, fixture_tables())
    print("fixture written to", FIXTURES)
