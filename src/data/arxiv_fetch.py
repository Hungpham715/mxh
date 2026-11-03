"""Fetch arXiv cs.CL metadata through the official Atom API (export.arxiv.org/api/query)."""
from __future__ import annotations

import calendar
import re
import xml.etree.ElementTree as ET
from typing import Any

from src.common import RAW, CachedClient, log, write_jsonl

NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom",
      "os": "http://a9.com/-/spec/opensearch/1.1/"}


def _clean(s: str | None) -> str | None:
    if s is None:
        return None
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def parse_feed(xml_text: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    out = []
    for e in root.findall("a:entry", NS):
        id_url = e.findtext("a:id", default="", namespaces=NS)
        m = re.search(r"arxiv\.org/abs/([^v]+?)(v\d+)?$", id_url)
        if not m:
            continue
        arxiv_id = m.group(1)
        prim = e.find("arxiv:primary_category", NS)
        authors = []
        for i, a in enumerate(e.findall("a:author", NS), 1):
            authors.append({"position": i, "name": _clean(a.findtext("a:name", namespaces=NS)),
                            "raw_affiliation": _clean(a.findtext("arxiv:affiliation", namespaces=NS))})
        doi = e.findtext("arxiv:doi", namespaces=NS)
        out.append({
            "arxiv_id": arxiv_id,
            "title": _clean(e.findtext("a:title", namespaces=NS)),
            "abstract": _clean(e.findtext("a:summary", namespaces=NS)),
            "published": e.findtext("a:published", namespaces=NS),
            "primary_category": prim.get("term") if prim is not None else None,
            "journal_doi": doi.lower().strip() if doi else None,
            "url": f"https://arxiv.org/abs/{arxiv_id}",
            "authors": authors,
        })
    return out


def fetch_arxiv(scope: dict[str, Any]) -> list[dict[str, Any]]:
    cfg = scope["arxiv"]
    client = CachedClient("arxiv", min_interval=cfg["delay_seconds"], timeout=90)
    per_month, page = cfg["per_month"], cfg["page_size"]
    selected: list[dict[str, Any]] = []
    for year in scope["years"]:
        for month in range(1, 13):
            last = calendar.monthrange(year, month)[1]
            q = (f"cat:{cfg['category']} AND submittedDate:[{year}{month:02d}010000 TO "
                 f"{year}{month:02d}{last}2359]")
            got: list[dict[str, Any]] = []
            start = 0
            while len(got) < per_month and start < 500:
                body = client.get(cfg["api_url"], params={
                    "search_query": q, "start": start, "max_results": page,
                    "sortBy": "submittedDate", "sortOrder": "ascending"})
                assert body is not None
                entries = parse_feed(body)
                if not entries:
                    break
                for ent in entries:
                    if ent["primary_category"] == cfg["category"] and ent["title"] and ent["authors"]:
                        if int(ent["published"][:4]) == year:
                            got.append(ent)
                    if len(got) >= per_month:
                        break
                start += page
            for g in got:
                g["year"] = year
                g["source_kind"] = "arxiv"
            log.info("arXiv %d-%02d: %d selected", year, month, len(got))
            selected.extend(got)
    # dedupe by arxiv id, keep first
    seen, uniq = set(), []
    for s in selected:
        if s["arxiv_id"] not in seen:
            seen.add(s["arxiv_id"])
            uniq.append(s)
    write_jsonl(RAW / "arxiv_selected.jsonl", uniq)
    return uniq
