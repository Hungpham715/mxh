#!/usr/bin/env python3
"""Independently review the held-out QA queue without claiming human provenance.

The pass combines three checks that are separate from candidate generation:
1. a fresh read-only execution of every catalogued query against Aura;
2. question/intent/entity semantics checked from the exported review text;
3. each cited primary paper landing page is reachable and its title agrees with
   the source title stored in the graph fact.

The resulting CSV is intended for ``independent_approved`` import only.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import html
import json
import re
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from datasets.auto_review import validate_cases_against_graph
from datasets.export_review import FIELDS
from datasets.io import read_models
from datasets.schema import QuestionCase


class MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, list[str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "meta":
            return
        values = {key.casefold(): value or "" for key, value in attrs}
        key = values.get("name", "").casefold()
        if key.startswith("citation_"):
            self.values.setdefault(key, []).append(html.unescape(values.get("content", "")).strip())


def canonical(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def compact(value: str) -> str:
    return canonical(value).replace(" ", "")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch_metadata(url: str, cache: Path) -> dict[str, Any]:
    target = cache / f"{hashlib.sha256(url.encode()).hexdigest()[:20]}.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or not target.stat().st_size:
        request = urllib.request.Request(
            url, headers={"User-Agent": "GraphRAG-independent-QA-review/1.0 (academic audit)"}
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                target.write_bytes(response.read())
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            return {"url": url, "ok": False, "error": f"{type(error).__name__}:{error}"}
    parser = MetadataParser()
    parser.feed(target.read_text(encoding="utf-8", errors="replace"))
    return {
        "url": url,
        "ok": True,
        "sha256": sha256(target),
        "title": (parser.values.get("citation_title") or [""])[0],
        "authors": parser.values.get("citation_author", []),
        "venue": (parser.values.get("citation_conference_title") or [""])[0],
    }


KEYWORDS: dict[str, tuple[str, ...]] = {
    "author_affiliations": ("cơ quan", "tổ chức", "affiliation"),
    "author_papers": ("bài báo", "papers", "công trình"),
    "author_path": ("đường", "path"),
    "coauthor_affiliations": ("đồng tác giả", "cơ quan"),
    "coauthors": ("đồng tác giả", "coauthor", "viết bài cùng"),
    "network_top": ("xếp hạng", "top", "nhiều cộng tác viên"),
    "org_collaborations": ("cơ quan", "tổ chức", "hợp tác", "đồng xuất hiện"),
    "paper_authors": ("tác giả", "authors"),
    "paper_citations": ("citation", "trích dẫn"),
    "paper_venue": ("venue", "xuất hiện", "công bố"),
    "shared_papers": ("bài báo chung", "công trình chung", "shared paper", "công trình nào"),
    "topic_papers": ("chủ đề", "topic", "gắn nhãn"),
}


def source_titles(case: QuestionCase) -> dict[str, set[str]]:
    output: dict[str, set[str]] = {}
    for fact in case.verified_facts:
        value = fact.get("value") or {}
        for source in value.get("sources") or []:
            url = str(source.get("url") or "")
            title = str(source.get("title") or value.get("paper_title") or "")
            if url:
                output.setdefault(url, set()).add(title)
    return output


def semantic_checks(case: QuestionCase, metadata: dict[str, dict[str, Any]]) -> dict[str, bool]:
    question = canonical(case.question)
    intent = case.expected_query.intent
    mentions_ok = all(canonical(mention.text) in question for mention in case.entity_mentions)
    keywords_ok = any(canonical(keyword) in question for keyword in KEYWORDS[intent])
    template_ok = case.template_id.split(".", 1)[0] == intent
    answer_ok = (
        bool(case.expected_facts.answer.strip()) and bool(case.verified_facts)
        if case.expected_status in {"answered", "partial"}
        else not case.expected_facts.answer.strip() and not case.verified_facts
    )
    titles = source_titles(case)
    citations_ok = set(case.expected_citations.source_urls) == set(titles)
    primary_ok = True
    for url in case.expected_citations.source_urls:
        observed = metadata[url]
        if not observed.get("ok") or not observed.get("title"):
            primary_ok = False
            continue
        expected = {compact(title) for title in titles.get(url, set()) if title}
        primary_ok = primary_ok and (not expected or compact(observed["title"]) in expected)
    return {
        "mentions": mentions_ok,
        "keywords": keywords_ok,
        "template": template_ok,
        "answer_contract": answer_ok,
        "citation_contract": citations_ok,
        "primary_metadata": primary_ok,
    }


async def run(args: argparse.Namespace) -> None:
    all_cases = read_models(args.source, QuestionCase)
    by_id = {case.case_id: case for case in all_cases}
    with args.queue.open(encoding="utf-8-sig", newline="") as handle:
        queue_rows = list(csv.DictReader(handle))
    missing = [row["case_id"] for row in queue_rows if row["case_id"] not in by_id]
    if missing:
        raise ValueError(f"queue contains unknown case IDs: {missing[:5]}")
    cases = [by_id[row["case_id"]] for row in queue_rows]

    graph_rows, graph_stats = await validate_cases_against_graph(
        cases, provider="neo4j", execute=True
    )
    graph_by_id = {row["case_id"]: row for row in graph_rows}

    source_urls = sorted(
        {url for case in cases for url in case.expected_citations.source_urls}
    )
    metadata: dict[str, dict[str, Any]] = {}
    for index, url in enumerate(source_urls, start=1):
        print(f"primary source {index}/{len(source_urls)} {url}", flush=True)
        metadata[url] = fetch_metadata(url, args.cache)

    reviewed: list[dict[str, str]] = []
    evidence: list[dict[str, Any]] = []
    for case in cases:
        graph_row = graph_by_id[case.case_id]
        checks = semantic_checks(case, metadata)
        graph_ok = graph_row["label_valid"] == "yes"
        valid = graph_ok and all(checks.values())
        failed = [name for name, passed in checks.items() if not passed]
        if not graph_ok:
            failed.insert(0, graph_row["reviewer_note"].removeprefix("silver_auto:"))
        note = (
            "independent_codex:graph_exact+question_semantics+primary_source_metadata"
            if valid
            else "independent_codex:failed:" + ",".join(failed)
        )
        row = dict(graph_row)
        row["label_valid"] = "yes" if valid else "no"
        row["reviewer_note"] = note
        reviewed.append(row)
        evidence.append(
            {
                "case_id": case.case_id,
                "decision": row["label_valid"],
                "graph_requery": graph_ok,
                "checks": checks,
                "sources": [metadata[url] for url in case.expected_citations.source_urls],
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(reviewed)
    args.evidence.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in evidence),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "cases": len(cases),
                "graph_requery": graph_stats,
                "decisions": Counter(row["label_valid"] for row in reviewed),
                "output_sha256": sha256(args.output),
                "evidence_sha256": sha256(args.evidence),
            },
            default=dict,
            ensure_ascii=False,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
