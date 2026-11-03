"""Data contract v1 (architecture.md section 3): row models, file list and dataset validator.

B-side code (graph loader) imports this module and must not modify it.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from src.common import read_json, read_jsonl, sha256_file
from src.data.topics import normalize as _norm

SCHEMA_VERSION = 1
YEARS = (2023, 2024, 2025)
TOPIC_IDS = ("llm", "mt", "qa", "retrieval", "summarization", "safety_eval")
ID_RE = re.compile(r"^(oa|acl|arxiv|src|venue|topic):\S+$")


def _ns(v: str) -> str:
    if not ID_RE.match(v):
        raise ValueError(f"id without namespace: {v!r}")
    return v


class Row(BaseModel):
    model_config = ConfigDict(extra="allow")


class PaperRow(Row):
    id: str
    title: str = Field(min_length=1)
    year: int
    abstract: Optional[str]
    doi: Optional[str]
    acl_id: Optional[str]
    arxiv_id: Optional[str]
    source_kind: Literal["acl", "arxiv"]
    source_url: str
    venue_id: str
    openalex_id: Optional[str]

    _id = field_validator("id", "venue_id")(_ns)

    @field_validator("year")
    @classmethod
    def _year(cls, v: int) -> int:
        if v not in YEARS:
            raise ValueError(f"year {v} out of scope")
        return v

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("blank title")
        return v


class AuthorRow(Row):
    id: str
    name: str = Field(min_length=1)
    orcid: Optional[str]
    openalex_id: Optional[str]
    acl_author_id: Optional[str]
    identity_status: Literal["verified", "source_only", "unresolved"]
    _id = field_validator("id")(_ns)


class InstitutionRow(Row):
    id: str
    name: str = Field(min_length=1)
    ror: Optional[str]
    country_code: Optional[str]
    source_url: str

    @field_validator("id")
    @classmethod
    def _oa(cls, v: str) -> str:
        if not v.startswith("oa:I"):
            raise ValueError("institution id must be an OpenAlex I-id")
        return v


class VenueRow(Row):
    id: str
    name: str
    kind: Literal["conference", "preprint_server"]
    year: Optional[int]
    source_url: str
    _id = field_validator("id")(_ns)


class PaperAuthorRow(Row):
    paper_id: str
    author_id: str
    position: int = Field(ge=1)
    author_position: Literal["first", "middle", "last"]
    source_url: str


class AffiliationRow(Row):
    paper_id: str
    author_id: str
    institution_id: str
    year: int
    raw_affiliation: Optional[str]
    source_url: str


class CitationRow(Row):
    citing_paper_id: str
    cited_paper_id: str
    source_url: str


class PaperTopicRow(Row):
    paper_id: str
    topic_id: Literal["llm", "mt", "qa", "retrieval", "summarization", "safety_eval"]
    rule_id: str
    evidence_span: str = Field(min_length=1)
    confidence_band: Literal["rule_high", "reviewed"]


FILES: dict[str, tuple[type[Row], tuple[str, ...]]] = {
    "papers.jsonl": (PaperRow, ("id",)),
    "authors.jsonl": (AuthorRow, ("id",)),
    "institutions.jsonl": (InstitutionRow, ("id",)),
    "venues.jsonl": (VenueRow, ("id",)),
    "paper_authors.jsonl": (PaperAuthorRow, ("paper_id", "author_id")),
    "affiliations.jsonl": (AffiliationRow, ("paper_id", "author_id", "institution_id")),
    "citations.jsonl": (CitationRow, ("citing_paper_id", "cited_paper_id")),
    "paper_topics.jsonl": (PaperTopicRow, ("paper_id", "topic_id")),
}
MANIFEST_KEYS = ("schema_version", "scope_id", "created_at_utc", "source_versions", "input_counts",
                 "output_counts", "unmatched_openalex_count", "checksums")


class ContractError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__(f"{len(errors)} contract error(s); first: {errors[:5]}")
        self.errors = errors


def load_dataset(data_dir: Path, check_manifest: bool = True) -> dict[str, list[dict[str, Any]]]:
    """Validate the 8 JSONL files (+ manifest) and return rows. Raises ContractError on any problem."""
    errors: list[str] = []
    data_dir = Path(data_dir)
    if check_manifest:
        mpath = data_dir / "manifest.json"
        if not mpath.exists():
            raise ContractError(["manifest.json missing"])
        manifest = read_json(mpath)
        for k in MANIFEST_KEYS:
            if k not in manifest:
                errors.append(f"manifest missing key {k}")
        if manifest.get("schema_version") != SCHEMA_VERSION:
            errors.append(f"schema_version {manifest.get('schema_version')} != {SCHEMA_VERSION}")
        for fname in FILES:
            f = data_dir / fname
            if not f.exists():
                errors.append(f"{fname} missing")
                continue
            want = manifest.get("checksums", {}).get(fname)
            if want != sha256_file(f):
                errors.append(f"{fname}: sha256 mismatch with manifest")
        if errors:
            raise ContractError(errors)

    rows: dict[str, list[dict[str, Any]]] = {}
    for fname, (model, key) in FILES.items():
        f = data_dir / fname
        if not f.exists():
            errors.append(f"{fname} missing")
            rows[fname] = []
            continue
        data = read_jsonl(f)
        seen: set[tuple[Any, ...]] = set()
        for i, r in enumerate(data, 1):
            try:
                model.model_validate(r)
            except ValidationError as exc:
                errors.append(f"{fname}:{i}: {exc.errors()[0]['loc']} {exc.errors()[0]['msg']}")
            k = tuple(r.get(x) for x in key)
            if k in seen:
                errors.append(f"{fname}:{i}: duplicate key {k}")
            seen.add(k)
        rows[fname] = data

    papers = {p["id"]: p for p in rows["papers.jsonl"]}
    authors = {a["id"] for a in rows["authors.jsonl"]}
    insts = {i["id"] for i in rows["institutions.jsonl"]}
    venues = {v["id"] for v in rows["venues.jsonl"]}
    # alias uniqueness: one OpenAlex work / DOI appears once
    for alias in ("openalex_id", "doi", "acl_id", "arxiv_id"):
        vals = [p[alias] for p in papers.values() if p.get(alias)]
        if len(vals) != len(set(vals)):
            errors.append(f"papers: duplicate {alias} alias")
    for p in papers.values():
        if p["venue_id"] not in venues:
            errors.append(f"paper {p['id']}: unknown venue {p['venue_id']}")
    authorships = set()
    per_paper_positions: dict[str, list[int]] = {}
    for r in rows["paper_authors.jsonl"]:
        if r["paper_id"] not in papers:
            errors.append(f"paper_authors: unknown paper {r['paper_id']}")
        if r["author_id"] not in authors:
            errors.append(f"paper_authors: unknown author {r['author_id']}")
        authorships.add((r["paper_id"], r["author_id"]))
        per_paper_positions.setdefault(r["paper_id"], []).append(r["position"])
    for pid, pos in per_paper_positions.items():
        if sorted(pos) != list(range(1, len(pos) + 1)):
            errors.append(f"paper_authors: positions of {pid} not 1..n")
    for r in rows["affiliations.jsonl"]:
        if (r["paper_id"], r["author_id"]) not in authorships:
            errors.append(f"affiliations: {r['author_id']} is not an author of {r['paper_id']}")
        if r["institution_id"] not in insts:
            errors.append(f"affiliations: unknown institution {r['institution_id']}")
        p = papers.get(r["paper_id"])
        if p and p["year"] != r["year"]:
            errors.append(f"affiliations: year mismatch for {r['paper_id']}")
    for r in rows["citations.jsonl"]:
        if r["citing_paper_id"] not in papers or r["cited_paper_id"] not in papers:
            errors.append(f"citations: endpoint outside corpus {r['citing_paper_id']}->{r['cited_paper_id']}")
        if r["citing_paper_id"] == r["cited_paper_id"]:
            errors.append(f"citations: self-citation {r['citing_paper_id']}")
    topic_count: dict[str, int] = {}
    for r in rows["paper_topics.jsonl"]:
        p = papers.get(r["paper_id"])
        if p is None:
            errors.append(f"paper_topics: unknown paper {r['paper_id']}")
            continue
        topic_count[r["paper_id"]] = topic_count.get(r["paper_id"], 0) + 1
        hay = _norm(f"{p['title']} {p.get('abstract') or ''}")
        if _norm(r["evidence_span"]) not in hay:
            errors.append(f"paper_topics: span {r['evidence_span']!r} not in title/abstract of {r['paper_id']}")
    for pid, n in topic_count.items():
        if n > 2:
            errors.append(f"paper_topics: {pid} has {n} topics (>2)")
    if errors:
        raise ContractError(errors)
    return rows
