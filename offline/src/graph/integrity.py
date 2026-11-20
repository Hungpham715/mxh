"""Full-graph integrity audit (gate G2): 100% of in-scope nodes and edges, no sampling.

Pure check functions live here so they can be unit-tested without a database; the CLI
`scripts/graph_integrity_audit.py` fetches live rows and calls them.

Checks performed on EVERY in-scope node/edge:
- label/type whitelist, exactly one owning label per node
- unique ids, scope_id present and equal to the project scope
- endpoint existence and endpoint labels per REL_SCHEMA
- duplicate (type, from, to) edges, self-loops
- canonical direction for symmetric types (COAUTHORED_WITH, ORG_COAUTHORED_WITH: from < to)
- evidence_paper_ids all reference in-scope Papers; evidence_count == len(evidence_paper_ids)
- year sanity (first_year <= last_year; Paper.year within the declared scope window)
- DOI / source_url syntax
- FIRST_AUTHOR_OF position == 1 and exactly one per paper; OTHER_AUTHOR_OF position > 1
- APPEARS_IN matches papers.venue_id and at most one per paper
- AFFILIATED_WITH supported by actual authorship on every evidence paper
- HAS_TOPIC present in paper_topics with a non-empty evidence_span
- CITES pair present in citations.jsonl; no self-citation
- RESEARCHES / ACTIVE_IN evidence_count >= MIN_TOPIC_PAPERS
- DB (label,id) node set and (type,from,to) edge set EQUAL the deterministic snapshot
  (processed JSONL + derive_edges), in both directions (missing / extra)
"""
from __future__ import annotations

import csv
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from src.common import SCOPE_ID, log, write_json
from src.graph.derive import MIN_TOPIC_PAPERS, REL_SCHEMA, REL_TYPES, derive_edges, topic_nodes

LABELS = ("Author", "Paper", "Institution", "Venue", "Topic")
SYMMETRIC_TYPES = {"COAUTHORED_WITH", "ORG_COAUTHORED_WITH"}
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
IDENTITY_STATUSES = {"verified", "source_only", "unresolved"}

REQUIRED_NODE_FIELDS = {
    "Author": ("name",),
    "Paper": ("title", "year"),
    "Institution": ("name",),
    "Venue": ("name",),
    "Topic": ("name", "topic_key"),
}


@dataclass
class AuditContext:
    """Snapshot-derived reference data used to check every live row."""

    node_label_of: dict[str, str]                      # id -> label (ids unique across labels)
    snapshot_node_keys: set[tuple[str, str]]           # (label, id)
    derived_edge_keys: set[tuple[str, str, str]]       # (type, from, to)
    paper_years: dict[str, int]
    paper_venue: dict[str, str]                        # paper_id -> venue_id
    authorship: set[tuple[str, str]]                   # (author_id, paper_id)
    paper_topics: dict[tuple[str, str], dict[str, Any]]  # (paper_id, topic_id) -> row
    citations: set[tuple[str, str]]                    # (citing, cited)
    scope_years: tuple[int, int] = (1900, 2100)

    @property
    def paper_ids(self) -> set[str]:
        return {i for i, l in self.node_label_of.items() if l == "Paper"}


@dataclass
class AuditErrors:
    node_errors: list[dict[str, Any]] = field(default_factory=list)
    edge_errors: list[dict[str, Any]] = field(default_factory=list)

    def add_node(self, check: str, node_id: str, detail: str) -> None:
        self.node_errors.append({"check": check, "id": node_id, "detail": detail})

    def add_edge(self, check: str, rel_type: str, src: str, dst: str, detail: str) -> None:
        self.edge_errors.append(
            {"check": check, "type": rel_type, "from": src, "to": dst, "detail": detail}
        )

    @property
    def total(self) -> int:
        return len(self.node_errors) + len(self.edge_errors)


def build_context(rows: dict[str, list[dict[str, Any]]], scope_years: tuple[int, int]) -> AuditContext:
    """Build the reference context from validated processed tables (same inputs as the importer)."""
    node_label_of: dict[str, str] = {}
    snapshot_node_keys: set[tuple[str, str]] = set()
    table_label = {
        "papers.jsonl": "Paper",
        "authors.jsonl": "Author",
        "institutions.jsonl": "Institution",
        "venues.jsonl": "Venue",
    }
    for table, label in table_label.items():
        for row in rows[table]:
            node_label_of[row["id"]] = label
            snapshot_node_keys.add((label, row["id"]))
    for topic in topic_nodes("topics-v1.0"):
        node_label_of[topic["id"]] = "Topic"
        snapshot_node_keys.add(("Topic", topic["id"]))

    # Integrity audits are read-only diagnostics; deriving expected edge keys must not rewrite
    # the pipeline's rejection artifacts as a side effect.
    edges = derive_edges(rows, write_rejections=False)
    derived_edge_keys = {
        (rtype, edge["from"], edge["to"]) for rtype in REL_TYPES for edge in edges[rtype]
    }

    authorship = {(r["author_id"], r["paper_id"]) for r in rows["paper_authors.jsonl"]}
    paper_topics = {
        (r["paper_id"], r["topic_id"]): r for r in rows["paper_topics.jsonl"]
    }
    citations = {(r["citing_paper_id"], r["cited_paper_id"]) for r in rows["citations.jsonl"]}
    return AuditContext(
        node_label_of=node_label_of,
        snapshot_node_keys=snapshot_node_keys,
        derived_edge_keys=derived_edge_keys,
        paper_years={p["id"]: p["year"] for p in rows["papers.jsonl"]},
        paper_venue={p["id"]: p["venue_id"] for p in rows["papers.jsonl"]},
        authorship=authorship,
        paper_topics=paper_topics,
        citations=citations,
        scope_years=scope_years,
    )


def url_ok(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def check_node(node: dict[str, Any], ctx: AuditContext, errors: AuditErrors) -> None:
    """Run all invariants for one live node row {id, labels, props}."""
    node_id = str(node.get("id") or "")
    labels = [l for l in node.get("labels", [])]
    props = node.get("props", {})

    known = [l for l in labels if l in LABELS]
    if len(known) != 1:
        errors.add_node("label_whitelist", node_id, f"expected exactly one known label, got {labels}")
        return
    label = known[0]

    if not node_id:
        errors.add_node("id_missing", node_id, "empty id")
        return
    if ctx.node_label_of.get(node_id) != label:
        errors.add_node(
            "snapshot_mismatch", node_id,
            f"live label {label} not in snapshot as ({label}, {node_id})",
        )

    if props.get("scope_id") != SCOPE_ID:
        errors.add_node("scope_id", node_id, f"scope_id={props.get('scope_id')!r}")

    for field_name in REQUIRED_NODE_FIELDS[label]:
        value = props.get(field_name)
        if value is None or value == "" or value == []:
            errors.add_node("required_field", node_id, f"{label}.{field_name} missing")

    if label == "Paper":
        year = props.get("year")
        if not isinstance(year, int):
            errors.add_node("year_type", node_id, f"year={year!r} is not an int")
        else:
            lo, hi = ctx.scope_years
            if not (lo <= year <= hi):
                errors.add_node("year_out_of_scope", node_id, f"year {year} outside [{lo},{hi}]")

    if label == "Author":
        status = props.get("identity_status")
        if status is not None and status not in IDENTITY_STATUSES:
            errors.add_node("identity_status", node_id, f"unknown identity_status {status!r}")

    doi = props.get("doi")
    if doi and not DOI_RE.match(str(doi)):
        errors.add_node("doi_syntax", node_id, f"doi={doi!r}")

    source_url = props.get("source_url")
    if source_url and not url_ok(str(source_url)):
        errors.add_node("source_url_syntax", node_id, f"source_url={source_url!r}")


def check_edge(
    edge: dict[str, Any],
    ctx: AuditContext,
    errors: AuditErrors,
    state: dict[str, Any],
) -> None:
    """Run all invariants for one live edge row {type, from, to, props}.

    `state` carries cross-row accumulators (seen keys, first-author counts, appears-in counts).
    """
    rel_type = str(edge.get("type") or "")
    src = str(edge.get("from") or "")
    dst = str(edge.get("to") or "")
    props = edge.get("props", {})

    if rel_type not in REL_TYPES:
        errors.add_edge("type_whitelist", rel_type, src, dst, "relationship type not in whitelist")
        return

    key = (rel_type, src, dst)
    if key in state["seen_edges"]:
        errors.add_edge("duplicate_edge", rel_type, src, dst, "duplicate (type, from, to)")
    state["seen_edges"].add(key)

    if key not in ctx.derived_edge_keys:
        errors.add_edge("not_in_snapshot", rel_type, src, dst, "edge absent from deterministic snapshot")

    if rel_type not in state["edge_type_counts"]:
        state["edge_type_counts"][rel_type] = 0
    state["edge_type_counts"][rel_type] += 1

    from_label = ctx.node_label_of.get(src)
    to_label = ctx.node_label_of.get(dst)
    expected_from, expected_to, _undirected = REL_SCHEMA[rel_type]
    if from_label is None or to_label is None:
        errors.add_edge("endpoint_missing", rel_type, src, dst,
                        f"endpoint not among snapshot nodes ({from_label}, {to_label})")
        return
    if (from_label, to_label) != (expected_from, expected_to):
        errors.add_edge("endpoint_label", rel_type, src, dst,
                        f"endpoints ({from_label},{to_label}) != schema ({expected_from},{expected_to})")

    if src == dst:
        errors.add_edge("self_loop", rel_type, src, dst, "self relationship")

    if rel_type in SYMMETRIC_TYPES and src > dst:
        errors.add_edge("canonical_direction", rel_type, src, dst, "symmetric edge not canonical (from < to)")

    if props.get("scope_id") != SCOPE_ID:
        errors.add_edge("scope_id", rel_type, src, dst, f"scope_id={props.get('scope_id')!r}")

    evidence = props.get("evidence_paper_ids") or []
    if not isinstance(evidence, list):
        errors.add_edge("evidence_type", rel_type, src, dst, "evidence_paper_ids is not a list")
        evidence = []
    paper_ids = ctx.paper_ids
    missing = [pid for pid in evidence if pid not in paper_ids]
    if missing:
        errors.add_edge("evidence_unknown_paper", rel_type, src, dst,
                        f"{len(missing)} evidence paper ids not in scope, e.g. {missing[:3]}")
    evidence_count = props.get("evidence_count")
    if evidence_count is not None and evidence_count != len(evidence):
        errors.add_edge("evidence_count_mismatch", rel_type, src, dst,
                        f"evidence_count={evidence_count} != len(evidence_paper_ids)={len(evidence)}")

    first_year, last_year = props.get("first_year"), props.get("last_year")
    if isinstance(first_year, int) and isinstance(last_year, int) and first_year > last_year:
        errors.add_edge("year_order", rel_type, src, dst, f"first_year {first_year} > last_year {last_year}")

    source_url = props.get("source_url")
    if source_url and not url_ok(str(source_url)):
        errors.add_edge("source_url_syntax", rel_type, src, dst, f"source_url={source_url!r}")

    # Type-specific invariants
    if rel_type == "FIRST_AUTHOR_OF":
        if props.get("position") != 1:
            errors.add_edge("first_author_position", rel_type, src, dst,
                            f"position={props.get('position')!r} != 1")
        state["first_author_per_paper"][dst] = state["first_author_per_paper"].get(dst, 0) + 1
    elif rel_type == "OTHER_AUTHOR_OF":
        position = props.get("position")
        if not isinstance(position, int) or position <= 1:
            errors.add_edge("other_author_position", rel_type, src, dst, f"position={position!r} <= 1")
    elif rel_type == "APPEARS_IN":
        # APPEARS_IN is Paper -> Venue: each paper (src) must appear in at most one venue.
        state["appears_in_per_paper"][src] = state["appears_in_per_paper"].get(src, 0) + 1
        expected_venue = ctx.paper_venue.get(src)
        if expected_venue is not None and dst != expected_venue:
            errors.add_edge("appears_in_venue_mismatch", rel_type, src, dst,
                            f"snapshot venue is {expected_venue}")
    elif rel_type == "AFFILIATED_WITH":
        unsupported = [pid for pid in evidence if (src, pid) not in ctx.authorship]
        if unsupported:
            errors.add_edge("affiliation_without_authorship", rel_type, src, dst,
                            f"{len(unsupported)} evidence papers not authored by src, e.g. {unsupported[:3]}")
    elif rel_type == "HAS_TOPIC":
        topic_id = dst.split(":", 1)[1] if dst.startswith("topic:") else dst
        row = ctx.paper_topics.get((src, topic_id))
        if row is None:
            errors.add_edge("topic_without_evidence_row", rel_type, src, dst,
                            "no paper_topics row for (paper, topic)")
        elif not str(props.get("evidence_span") or "").strip():
            errors.add_edge("topic_evidence_span_missing", rel_type, src, dst, "empty evidence_span")
    elif rel_type == "CITES":
        if (src, dst) not in ctx.citations:
            errors.add_edge("citation_without_source_row", rel_type, src, dst,
                            "pair not in citations.jsonl")
    elif rel_type in {"RESEARCHES", "ACTIVE_IN"}:
        if not isinstance(evidence_count, int) or evidence_count < MIN_TOPIC_PAPERS:
            errors.add_edge("inferred_relation_threshold", rel_type, src, dst,
                            f"evidence_count={evidence_count!r} < {MIN_TOPIC_PAPERS}")


def finalize_edge_checks(state: dict[str, Any], ctx: AuditContext, errors: AuditErrors) -> None:
    """Cross-row invariants that need the full scan (cardinality, set equality)."""
    for paper_id, count in state["first_author_per_paper"].items():
        if count != 1:
            errors.add_edge("first_author_cardinality", "FIRST_AUTHOR_OF", "?", paper_id,
                            f"{count} first authors (expected exactly 1)")
    for paper_id, count in state["appears_in_per_paper"].items():
        if count > 1:
            errors.add_edge("appears_in_cardinality", "APPEARS_IN", paper_id, "?",
                            f"{count} venues (expected <= 1)")

    missing_edges = ctx.derived_edge_keys - state["seen_edges"]
    for rel_type, src, dst in sorted(missing_edges):
        errors.add_edge("missing_from_db", rel_type, src, dst, "snapshot edge absent from live DB")


def new_edge_state() -> dict[str, Any]:
    return {
        "seen_edges": set(),
        "edge_type_counts": {},
        "first_author_per_paper": {},
        "appears_in_per_paper": {},
    }


def check_snapshot_node_coverage(
    live_node_keys: set[tuple[str, str]], ctx: AuditContext, errors: AuditErrors
) -> None:
    missing = ctx.snapshot_node_keys - live_node_keys
    extra = live_node_keys - ctx.snapshot_node_keys
    for label, node_id in sorted(missing):
        errors.add_node("missing_from_db", node_id, f"snapshot node ({label}, {node_id}) absent from live DB")
    for label, node_id in sorted(extra):
        errors.add_node("extra_in_db", node_id, f"live node ({label}, {node_id}) absent from snapshot")


def write_error_csvs(out_dir: Path, errors: AuditErrors) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    node_path = out_dir / "node_errors.csv"
    edge_path = out_dir / "edge_errors.csv"
    with node_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["check", "id", "detail"], lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(errors.node_errors)
    with edge_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["check", "type", "from", "to", "detail"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(errors.edge_errors)
    return node_path, edge_path


def build_report(
    *,
    live_counts: dict[str, int],
    scanned: dict[str, int],
    nodes_by_label: dict[str, int],
    state: dict[str, Any],
    errors: AuditErrors,
    database_label: str,
) -> dict[str, Any]:
    counts_match_live = (
        scanned["nodes"] == live_counts["scoped_nodes"]
        and scanned["edges"] == live_counts["scoped_edges"]
    )
    error_checks: dict[str, int] = {}
    for row in errors.node_errors:
        error_checks[row["check"]] = error_checks.get(row["check"], 0) + 1
    for row in errors.edge_errors:
        error_checks[row["check"]] = error_checks.get(row["check"], 0) + 1
    result = "PASS" if errors.total == 0 and counts_match_live else "FAIL"
    return {
        "audit": "graph_integrity_all",
        "scope_id": SCOPE_ID,
        "database": database_label,
        "finished_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "live_counts": live_counts,
        "scanned": scanned,
        "counts_match_live": counts_match_live,
        "nodes_by_label": nodes_by_label,
        "edges_by_type": state["edge_type_counts"],
        "node_errors": len(errors.node_errors),
        "edge_errors": len(errors.edge_errors),
        "errors_by_check": error_checks,
        "sample_errors": (errors.node_errors[:10] + errors.edge_errors[:10]),
        "result": result,
    }


def iter_batches(items: Iterable[Any], size: int) -> Iterable[list[Any]]:
    batch: list[Any] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


_ = write_json  # re-exported for the CLI; kept imported here for a single dependency surface
_ = log
