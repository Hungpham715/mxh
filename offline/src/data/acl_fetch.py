"""Fetch ACL Anthology paper metadata from the official XML files (acl-org/acl-anthology)."""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from typing import Any

from src.common import RAW, CachedClient, log, write_jsonl


def _text(el: ET.Element | None) -> str | None:
    """Flatten mixed-content XML (fixed-case, tex-math, url ...) into plain text."""
    if el is None:
        return None
    txt = "".join(el.itertext())
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt or None


def _author_name(el: ET.Element) -> str:
    first = _text(el.find("first")) or ""
    last = _text(el.find("last")) or ""
    return f"{first} {last}".strip()


def parse_collection(xml_text: str, collection: str, volume_id: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    out = []
    for vol in root.findall("volume"):
        if vol.get("id") != volume_id:
            continue
        meta = vol.find("meta")
        booktitle = _text(meta.find("booktitle")) if meta is not None else None
        year = int(_text(meta.find("year"))) if meta is not None and meta.find("year") is not None else None
        for p in vol.findall("paper"):
            pid = p.get("id")
            if pid is None or not pid.isdigit():
                continue
            acl_id = f"{collection}-{volume_id}.{pid}"
            # new-style ids: 2023.acl-long.1
            authors = []
            for i, a in enumerate(p.findall("author"), 1):
                authors.append({
                    "position": i,
                    "name": _author_name(a),
                    "acl_author_id": a.get("id"),
                    "orcid": a.get("orcid"),
                    "raw_affiliation": _text(a.find("affiliation")),
                })
            out.append({
                "acl_id": acl_id,
                "paper_num": int(pid),
                "collection": collection,
                "volume": volume_id,
                "volume_title": booktitle,
                "year": year,
                "title": _text(p.find("title")),
                "abstract": _text(p.find("abstract")),
                "doi": (_text(p.find("doi")) or "").lower() or None,
                "url": f"https://aclanthology.org/{acl_id}/",
                "authors": authors,
            })
    return out


def systematic_sample(items: list[dict[str, Any]], quota: int) -> list[dict[str, Any]]:
    items = sorted(items, key=lambda r: r["paper_num"])
    n = len(items)
    if n <= quota:
        return items
    return [items[(i * n) // quota] for i in range(quota)]


def fetch_acl(scope: dict[str, Any]) -> list[dict[str, Any]]:
    cfg = scope["acl"]
    client = CachedClient("acl", min_interval=1.0, timeout=120)
    selected: list[dict[str, Any]] = []
    stats = []
    for spec in cfg["volumes"]:
        coll, vol, quota = spec["collection"], spec["volume"], spec["quota"]
        body = client.get(cfg["xml_url"].format(collection=coll))
        assert body is not None
        papers = parse_collection(body, coll, vol)
        papers = [p for p in papers if p["title"] and p["authors"]]
        picked = systematic_sample(papers, quota)
        shortfall = quota - len(picked)
        stats.append({"collection": coll, "volume": vol, "available": len(papers), "selected": len(picked),
                      "shortfall": shortfall})
        log.info("ACL %s-%s: %d available, %d selected", coll, vol, len(papers), len(picked))
        if shortfall > 0:
            log.warning("ACL %s-%s short by %d; Findings fallback would be needed", coll, vol, shortfall)
        fetched_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for p in picked:
            p["fetched_at_utc"] = fetched_at
            p["source_kind"] = "acl"
        selected.extend(picked)
    write_jsonl(RAW / "acl_selected.jsonl", selected)
    write_jsonl(RAW / "acl_selection_stats.jsonl", stats)
    return selected
