#!/usr/bin/env python3
"""Build an auditable, source-first independent review packet.

This script does not call the graph derivation code and does not consume the
automated labels/scores.  It retrieves the paper landing pages and only the
PDFs needed for relationship claims that are not decidable from bibliographic
metadata.  Its output is evidence for an independent reviewer; it deliberately
uses ``unverifiable`` whenever the source does not support a strict decision.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import subprocess
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


PDF_TYPES = {"AFFILIATED_WITH", "ORG_COAUTHORED_WITH", "ACTIVE_IN", "CITES"}
TOPIC_TYPES = {"HAS_TOPIC", "RESEARCHES", "ACTIVE_IN"}


class MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, list[str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "meta":
            return
        values = {key.casefold(): value or "" for key, value in attrs}
        key = values.get("name", "").casefold()
        if key.startswith("citation_"):
            self.meta.setdefault(key, []).append(html.unescape(values.get("content", "")).strip())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.casefold().replace("&", " and ")
    return " ".join(re.findall(r"[a-z0-9]+", value))


def compact(value: str) -> str:
    return canonical(value).replace(" ", "")


def name_matches(expected: str, actual: str) -> bool:
    left, right = canonical(expected), canonical(actual)
    if left == right:
        return True
    lt, rt = left.split(), right.split()
    if len(lt) < 2 or len(rt) < 2:
        return False
    if lt[0] == rt[0] and lt[-1] == rt[-1]:
        return True
    # arXiv commonly serializes names as "Family, Given". Punctuation normalization loses
    # the comma, so use token containment to tolerate reversal and omitted middle names.
    left_tokens, right_tokens = set(lt), set(rt)
    return left_tokens <= right_tokens or right_tokens <= left_tokens


def org_variants(name: str) -> list[str]:
    cleaned = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
    variants = {canonical(name), canonical(cleaned)}
    aliases = {
        "adobe systems": ["adobe"],
        "ant group": ["ant group", "ant research"],
        "beijing university of posts and telecommunications": ["bupt"],
        "carnegie mellon university": ["cmu"],
        "chinese academy of sciences": ["cas"],
        "city university of hong kong shenzhen research institute": [
            "city university of hong kong shenzhen research institute",
            "cityu shenzhen research institute",
        ],
        "helmholtz center for information security": ["cispa"],
        "indian institute of technology bombay": ["iit bombay", "iitb"],
        "indian institute of technology hyderabad": ["iit hyderabad", "iith"],
        "institute of automation": ["institute of automation chinese academy of sciences"],
        "institute of computing technology": ["institute of computing technology chinese academy of sciences", "ict cas"],
        "microsoft": ["microsoft", "microsoft research"],
        "mohamed bin zayed university of artificial intelligence": ["mbzuai"],
        "nanyang technological university": ["ntu singapore", "nanyang technological university"],
        "national university of singapore": ["nus"],
        "singapore national eye center": ["singapore national eye centre", "snec"],
        "shenzhen institutes of advanced technology": ["siat"],
        "tencent": ["tencent"],
        "university of chinese academy of sciences": ["ucas"],
        "university college london": ["ucl"],
        "university of maryland college park": ["university of maryland", "umd"],
        "university of north carolina at chapel hill": ["unc chapel hill", "university of north carolina"],
        "university of texas at austin": ["ut austin", "the university of texas at austin"],
        "yale university": ["yale", "yale school of medicine"],
        "zhipu ai": ["zhipu ai", "zhipuai", "chatglm"],
    }
    variants.update(canonical(value) for value in aliases.get(canonical(cleaned), []))
    return sorted((value for value in variants if value), key=len, reverse=True)


def text_has_org(text: str, org: str) -> bool:
    normalized = canonical(text)
    dense = compact(text)
    return any(variant in normalized or variant.replace(" ", "") in dense for variant in org_variants(org))


def text_has_title(text: str, title: str) -> bool:
    haystack = compact(text)
    needle = compact(title)
    if needle and needle in haystack:
        return True
    tokens = canonical(title).split()
    meaningful = [token for token in tokens if len(token) >= 4]
    if len(meaningful) < 4:
        return False
    normalized = canonical(text)
    return sum(token in normalized for token in set(meaningful)) / len(set(meaningful)) >= 0.9


def topic_supported(topic: str, title: str, abstract: str) -> tuple[bool, str]:
    text = canonical(f"{title} {abstract}")
    rules = {
        "llm": ["large language model", "llm", "chatgpt", "language models"],
        "mt": ["machine translation", "speech translation", "translation"],
        "qa": ["question answering", "question answer", "reading comprehension"],
        "retrieval": ["retrieval", "retriever", "rag", "retrieval augmented"],
        "summarization": ["summarization", "summary", "summarize"],
        "safety_eval": [
            "jailbreak",
            "safety",
            "hallucination",
            "red teaming",
            "red team",
            "model evaluation",
            "evaluating language models",
            "evaluate language models",
        ],
    }
    key = topic.removeprefix("topic:")
    hits = [phrase for phrase in rules.get(key, []) if canonical(phrase) in text]
    return bool(hits), ",".join(hits[:4])


def fetch(url: str, target: Path, attempts: int = 3) -> tuple[bool, str]:
    if target.exists() and target.stat().st_size:
        return True, "cached"
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "GraphRAG-independent-review/1.0 (academic audit)"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read()
            target.write_bytes(body)
            time.sleep(0.15)
            return True, "downloaded"
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            if attempt + 1 == attempts:
                return False, f"{type(error).__name__}:{error}"
            time.sleep(1.0 + attempt)
    return False, "unreachable"


def urls(value: str) -> list[str]:
    return re.findall(r"https?://[^\s|]+", value)


def slug(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:20]


def pdf_url(page_url: str, meta: dict[str, list[str]]) -> str:
    values = meta.get("citation_pdf_url", [])
    if values:
        return values[0]
    if "arxiv.org/abs/" in page_url:
        return page_url.replace("/abs/", "/pdf/")
    return page_url.rstrip("/") + ".pdf"


def load_source(page_url: str, cache: Path, need_pdf: bool) -> dict[str, Any]:
    key = slug(page_url)
    html_path = cache / "html" / f"{key}.html"
    ok, detail = fetch(page_url, html_path)
    result: dict[str, Any] = {"url": page_url, "html_ok": ok, "html_detail": detail}
    if not ok:
        return result
    parser = MetadataParser()
    parser.feed(html_path.read_text(encoding="utf-8", errors="replace"))
    result.update(
        {
            "html_sha256": sha256(html_path),
            "title": (parser.meta.get("citation_title") or [""])[0],
            "authors": parser.meta.get("citation_author", []),
            "venue": (parser.meta.get("citation_conference_title") or [""])[0],
            "abstract": (parser.meta.get("citation_abstract") or [""])[0],
        }
    )
    if not result["abstract"]:
        raw = html_path.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"<div[^>]*acl-abstract[^>]*>.*?<span>(.*?)</span>", raw, re.I | re.S)
        if match:
            result["abstract"] = re.sub(r"<[^>]+>", " ", html.unescape(match.group(1))).strip()
    if not need_pdf:
        return result
    result["pdf_url"] = pdf_url(page_url, parser.meta)
    pdf_path = cache / "pdf" / f"{key}.pdf"
    ok, detail = fetch(result["pdf_url"], pdf_path)
    result.update({"pdf_ok": ok, "pdf_detail": detail})
    if not ok:
        return result
    result["pdf_sha256"] = sha256(pdf_path)
    text_path = cache / "text" / f"{key}.txt"
    text_path.parent.mkdir(parents=True, exist_ok=True)
    if not text_path.exists() or not text_path.stat().st_size:
        completed = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), str(text_path)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        if completed.returncode:
            result["pdf_text_error"] = completed.stderr.strip()
            return result
    result["pdf_text_sha256"] = sha256(text_path)
    result["pdf_text"] = text_path.read_text(encoding="utf-8", errors="replace")
    return result


def review_row(row: dict[str, str], sources: list[dict[str, Any]]) -> tuple[str, str, str]:
    relation = row["type"]
    if not sources or any(not source.get("html_ok") for source in sources):
        return "unverifiable", "", "source landing page unavailable"

    if relation == "FIRST_AUTHOR_OF":
        authors = sources[0].get("authors", [])
        return (
            ("correct", "", "primary metadata: first author matches")
            if authors and name_matches(row["from_name"], authors[0])
            else ("incorrect", "wrong_position", f"primary metadata first author={authors[:1]}")
        )
    if relation == "OTHER_AUTHOR_OF":
        authors = sources[0].get("authors", [])
        positions = [index for index, author in enumerate(authors) if name_matches(row["from_name"], author)]
        if any(index > 0 for index in positions):
            return "correct", "", f"primary metadata author positions={positions}"
        return "incorrect", "wrong_position", f"primary metadata author positions={positions}"
    if relation == "COAUTHORED_WITH":
        authors = sources[0].get("authors", [])
        left = any(name_matches(row["from_name"], author) for author in authors)
        right = any(name_matches(row["to_name"], author) for author in authors)
        return (
            ("correct", "", "both authors occur in primary author list")
            if left and right
            else ("incorrect", "wrong_author", f"author occurrence left={left} right={right}")
        )
    if relation == "APPEARS_IN":
        if "arxiv.org/" in sources[0]["url"]:
            valid = canonical(row["to_name"]) == canonical("arXiv cs.CL (preprint)")
            observed = "arXiv source page"
        else:
            observed = sources[0].get("venue", "")
            valid = canonical(observed) == canonical(row["to_name"])
        return (
            ("correct", "", f"primary venue={observed}")
            if valid
            else ("incorrect", "evidence_mismatch", f"primary venue={observed}")
        )
    if relation == "HAS_TOPIC":
        supported, hits = topic_supported(row["to_name"], sources[0].get("title", ""), sources[0].get("abstract", ""))
        return (
            ("correct", "", f"primary title/abstract topic evidence={hits}")
            if supported
            else ("incorrect", "evidence_mismatch", "no topic-definition evidence in primary title/abstract")
        )
    if relation == "CITES":
        text = sources[0].get("pdf_text", "")
        if not text:
            return "unverifiable", "", "source PDF text unavailable"
        valid = text_has_title(text, row["to_name"])
        return (
            ("correct", "", "target title occurs in source-paper PDF references")
            if valid
            else ("incorrect", "wrong_direction", "target title absent from source-paper PDF")
        )
    if relation == "AFFILIATED_WITH":
        for source in sources:
            text = source.get("pdf_text", "")[:30000]
            if any(name_matches(row["from_name"], author) for author in source.get("authors", [])) and text_has_org(text, row["to_name"]):
                return "correct", "", f"author list and target organization occur in paper front matter: {source['url']}"
        if any(not source.get("pdf_text") for source in sources):
            return "unverifiable", "", "one or more source PDFs unavailable"
        return "incorrect", "wrong_org", "target organization absent from paper front matter"
    if relation == "ORG_COAUTHORED_WITH":
        for source in sources:
            text = source.get("pdf_text", "")[:30000]
            if text_has_org(text, row["from_name"]) and text_has_org(text, row["to_name"]):
                return "correct", "", f"both organizations occur in paper front matter: {source['url']}"
        if any(not source.get("pdf_text") for source in sources):
            return "unverifiable", "", "one or more source PDFs unavailable"
        return "incorrect", "wrong_org", "one or both organizations absent from paper front matter"
    if relation == "RESEARCHES":
        count = 0
        details = []
        for source in sources:
            author_ok = any(name_matches(row["from_name"], author) for author in source.get("authors", []))
            topic_ok, hits = topic_supported(row["to_name"], source.get("title", ""), source.get("abstract", ""))
            details.append(f"{source['url']}:author={author_ok},topic={topic_ok}:{hits}")
            count += int(author_ok and topic_ok)
        return (
            ("correct", "", f"{count} primary papers support authorship+topic; " + "; ".join(details))
            if count >= 2
            else ("incorrect", "evidence_mismatch", f"only {count} primary papers support authorship+topic; " + "; ".join(details))
        )
    if relation == "ACTIVE_IN":
        count = 0
        details = []
        for source in sources:
            front = source.get("pdf_text", "")[:30000]
            org_ok = text_has_org(front, row["from_name"])
            topic_ok, hits = topic_supported(row["to_name"], source.get("title", ""), source.get("abstract", ""))
            details.append(f"{source['url']}:org={org_ok},topic={topic_ok}:{hits}")
            count += int(org_ok and topic_ok)
        if count >= 2:
            return "correct", "", f"{count} primary papers support organization+topic; " + "; ".join(details)
        if any(not source.get("pdf_text") for source in sources):
            return "unverifiable", "", f"only {count} verified and one or more PDFs unavailable; " + "; ".join(details)
        return "incorrect", "wrong_org" if any("org=False" in item for item in details) else "evidence_mismatch", f"only {count} primary papers support organization+topic; " + "; ".join(details)
    return "unverifiable", "", f"unsupported relationship type {relation}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--reviewer", default="codex-independent-source-review-v1")
    args = parser.parse_args()

    with args.input.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = list(rows[0])
    all_urls = sorted({url for row in rows for url in urls(row["evidence_urls"])})
    needs_pdf = {
        url
        for row in rows
        if row["type"] in PDF_TYPES
        for url in urls(row["evidence_urls"])
    }
    source_map: dict[str, dict[str, Any]] = {}
    for index, url in enumerate(all_urls, start=1):
        print(f"source {index}/{len(all_urls)} pdf={url in needs_pdf} {url}", flush=True)
        source_map[url] = load_source(url, args.cache, url in needs_pdf)

    reviewed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    evidence_rows: list[dict[str, Any]] = []
    for row in rows:
        row_sources = [source_map[url] for url in urls(row["evidence_urls"])]
        label, error_reason, note = review_row(row, row_sources)
        row.update(
            {
                "reviewer": args.reviewer,
                "reviewed_at_utc": reviewed_at,
                "label": label,
                "error_reason": error_reason,
                "note": note,
                "label_origin": "independent_source_review",
            }
        )
        evidence_rows.append(
            {
                "sample_id": row["sample_id"],
                "type": row["type"],
                "decision": label,
                "error_reason": error_reason,
                "note": note,
                "sources": [
                    {key: value for key, value in source.items() if key != "pdf_text"}
                    for source in row_sources
                ],
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    args.evidence.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in evidence_rows),
        encoding="utf-8",
    )
    print(json.dumps({"rows": len(rows), "labels": Counter(row["label"] for row in rows), "output_sha256": sha256(args.output), "evidence_sha256": sha256(args.evidence)}, default=dict, ensure_ascii=False))


if __name__ == "__main__":
    main()
