"""Enrich selected ACL/arXiv papers with OpenAlex single-work lookups by exact DOI."""
from __future__ import annotations

import json
from typing import Any

from src.common import RAW, CachedClient, env, log, write_jsonl


def doi_for(rec: dict[str, Any]) -> str | None:
    if rec["source_kind"] == "acl":
        return rec.get("doi")
    return f"10.48550/arxiv.{rec['arxiv_id']}".lower()


def make_client(scope: dict[str, Any]) -> CachedClient:
    key = env("OPENALEX_API_KEY")
    extra = {"api_key": key} if key else {}
    if not key:
        log.warning("OPENALEX_API_KEY not set: using unauthenticated OpenAlex access (lower limits)")
    return CachedClient("openalex", min_interval=scope["openalex"]["min_interval_seconds"], timeout=60,
                        extra_params=extra)


def enrich(scope: dict[str, Any], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base = (env("OPENALEX_BASE_URL") or scope["openalex"]["base_url"]).rstrip("/")
    client = make_client(scope)
    select = scope["openalex"]["select"]
    out, unmatched = [], []
    for i, rec in enumerate(records, 1):
        doi = doi_for(rec)
        work = None
        if doi:
            body = client.get(f"{base}/works/doi:{doi}", params={"select": select}, allow_404=True)
            work = json.loads(body) if body else None
        if work is None:
            unmatched.append({"source_kind": rec["source_kind"], "source_id": rec.get("acl_id") or rec.get("arxiv_id"),
                              "doi_tried": doi, "reason": "not_found" if doi else "no_doi"})
        out.append({"source_kind": rec["source_kind"],
                    "source_id": rec.get("acl_id") or rec.get("arxiv_id"),
                    "doi_tried": doi, "openalex": work})
        if i % 100 == 0:
            log.info("OpenAlex enrich %d/%d (unmatched so far %d)", i, len(records), len(unmatched))
    write_jsonl(RAW / "openalex_works.jsonl", out)
    write_jsonl(RAW / "openalex_unmatched.jsonl", unmatched)
    log.info("OpenAlex: %d matched, %d unmatched", len(records) - len(unmatched), len(unmatched))
    return out
