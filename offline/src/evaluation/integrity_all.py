"""Full-population (census) integrity audit of the scoped graph snapshot.

Every node and every edge of the snapshot is checked; nothing is sampled.
This is a *technical* audit (IDs, schema, endpoints, provenance, referential
invariants). It does NOT measure factual truth against the outside world;
that is the separate statistical truth audit (gate G3).

Input:  data/processed/*.jsonl (8 tables) + edges re-derived from them.
Output: <out>/integrity_all.json, node_errors.csv, edge_errors.csv
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.common import DERIVED, read_jsonl
from src.data.contracts import load_dataset
from src.graph.derive import MIN_TOPIC_PAPERS, REL_SCHEMA, REL_TYPES, TOPICS, derive_edges

URL_RE = re.compile(r"^https://[^\s/$.?#].[^\s]*$")
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
YEAR_MIN, YEAR_MAX = 2023, 2025
SYMMETRIC = {t for t, (_, _, undirected) in REL_SCHEMA.items() if undirected}

CRITICAL = "critical"
WARNING = "warning"


class Findings:
    def __init__(self) -> None:
        self.node_errors: list[dict[str, Any]] = []
        self.edge_errors: list[dict[str, Any]] = []

    def node(self, severity: str, label: str, node_id: str, check: str, detail: str = "") -> None:
        self.node_errors.append(
            {"severity": severity, "label": label, "id": node_id, "check": check, "detail": detail}
        )

    def edge(self, severity: str, edge: dict[str, Any], check: str, detail: str = "") -> None:
        self.edge_errors.append(
            {
                "severity": severity,
                "type": edge.get("type"),
                "from": edge.get("from"),
                "to": edge.get("to"),
                "check": check,
                "detail": detail,
            }
        )


def _node_tables(rows: dict[str, list[dict[str, Any]]], rule_version: str) -> dict[str, list[dict[str, Any]]]:
    topics = [{"id": f"topic:{key}", "name": name} for key, (name, _) in TOPICS.items()]
    _ = rule_version
    return {
        "Paper": rows["papers.jsonl"],
        "Author": rows["authors.jsonl"],
        "Institution": rows["institutions.jsonl"],
        "Venue": rows["venues.jsonl"],
        "Topic": topics,
    }


def audit_nodes(nodes: dict[str, list[dict[str, Any]]], findings: Findings) -> dict[str, int]:
    all_ids: Counter[str] = Counter()
    scanned: dict[str, int] = {}
    for label, records in nodes.items():
        scanned[label] = len(records)
        seen_in_label: set[str] = set()
        for record in records:
            node_id = record.get("id")
            if not node_id:
                findings.node(CRITICAL, label, "", "missing_id")
                continue
            if node_id in seen_in_label:
                findings.node(CRITICAL, label, node_id, "duplicate_id_in_label")
            seen_in_label.add(node_id)
            all_ids[node_id] += 1

            name_field = "title" if label == "Paper" else "name"
            name = record.get(name_field)
            if not isinstance(name, str) or not name.strip():
                findings.node(CRITICAL, label, node_id, f"missing_{name_field}")

            if label == "Paper":
                year = record.get("year")
                if not isinstance(year, int) or not YEAR_MIN <= year <= YEAR_MAX:
                    findings.node(CRITICAL, label, node_id, "year_out_of_scope", str(year))
                url = record.get("source_url")
                if not isinstance(url, str) or not URL_RE.match(url):
                    findings.node(CRITICAL, label, node_id, "bad_source_url", str(url))
                doi = record.get("doi")
                if doi is not None and not DOI_RE.match(str(doi)):
                    findings.node(WARNING, label, node_id, "bad_doi_syntax", str(doi))
                if record.get("source_kind") not in {"acl", "arxiv", "openalex"}:
                    findings.node(CRITICAL, label, node_id, "bad_source_kind", str(record.get("source_kind")))
            if label == "Institution":
                url = record.get("source_url")
                if url is not None and not URL_RE.match(str(url)):
                    findings.node(WARNING, label, node_id, "bad_source_url", str(url))
            if label == "Author" and record.get("identity_status") not in {
                "verified", "source_only", "ambiguous", "unresolved"
            }:
                findings.node(WARNING, label, node_id, "unexpected_identity_status",
                              str(record.get("identity_status")))

    for node_id, count in all_ids.items():
        if count > 1:
            findings.node(CRITICAL, "*", node_id, "id_reused_across_labels", str(count))
    return scanned


def _index(rows: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    authors_of: dict[str, dict[str, int]] = defaultdict(dict)
    for row in rows["paper_authors.jsonl"]:
        authors_of[row["paper_id"]][row["author_id"]] = row["position"]
    affil: set[tuple[str, str, str]] = set()
    insts_of_paper: dict[str, set[str]] = defaultdict(set)
    for row in rows["affiliations.jsonl"]:
        affil.add((row["paper_id"], row["author_id"], row["institution_id"]))
        insts_of_paper[row["paper_id"]].add(row["institution_id"])
    topics_of: dict[str, set[str]] = defaultdict(set)
    topic_rows: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows["paper_topics.jsonl"]:
        topic_id = f"topic:{row['topic_id']}"
        topics_of[row["paper_id"]].add(topic_id)
        topic_rows[(row["paper_id"], topic_id)] = row
    cites = {(row["citing_paper_id"], row["cited_paper_id"]) for row in rows["citations.jsonl"]}
    return {
        "authors_of": authors_of,
        "affil": affil,
        "insts_of_paper": insts_of_paper,
        "topics_of": topics_of,
        "topic_rows": topic_rows,
        "cites": cites,
    }


def _check_generic(edge: dict[str, Any], label_of: dict[str, str], papers: dict[str, dict[str, Any]],
                   findings: Findings) -> bool:
    """Schema/endpoint/provenance checks shared by all types. Returns False if endpoints are broken."""
    etype = edge.get("type")
    if etype not in REL_SCHEMA:
        findings.edge(CRITICAL, edge, "type_not_whitelisted")
        return False
    from_label, to_label, _ = REL_SCHEMA[etype]
    ok = True
    if label_of.get(edge["from"]) != from_label:
        findings.edge(CRITICAL, edge, "bad_from_endpoint", f"expected {from_label}")
        ok = False
    if label_of.get(edge["to"]) != to_label:
        findings.edge(CRITICAL, edge, "bad_to_endpoint", f"expected {to_label}")
        ok = False
    if edge["from"] == edge["to"]:
        findings.edge(CRITICAL, edge, "self_loop")
    evidence = edge.get("evidence_paper_ids") or []
    if not evidence:
        findings.edge(CRITICAL, edge, "no_evidence_papers")
    missing = [pid for pid in evidence if pid not in papers]
    if missing:
        findings.edge(CRITICAL, edge, "evidence_paper_missing", ",".join(missing[:3]))
    if edge.get("evidence_count") != len(evidence):
        findings.edge(CRITICAL, edge, "evidence_count_mismatch")
    url = edge.get("source_url")
    if not isinstance(url, str) or not URL_RE.match(url):
        findings.edge(CRITICAL, edge, "bad_source_url", str(url))
    expected_years = sorted({papers[pid]["year"] for pid in evidence if pid in papers})
    if edge.get("years") != expected_years:
        findings.edge(CRITICAL, edge, "years_inconsistent_with_evidence")
    return ok


def _check_semantics(edge: dict[str, Any], idx: dict[str, Any], papers: dict[str, dict[str, Any]],
                     findings: Findings) -> None:
    etype = edge["type"]
    src, dst = edge["from"], edge["to"]
    evidence = [pid for pid in edge.get("evidence_paper_ids") or [] if pid in papers]
    authors_of = idx["authors_of"]

    if etype == "FIRST_AUTHOR_OF":
        if authors_of.get(dst, {}).get(src) != 1:
            findings.edge(CRITICAL, edge, "not_position_1_author")
    elif etype == "OTHER_AUTHOR_OF":
        position = authors_of.get(dst, {}).get(src)
        if position is None or position <= 1:
            findings.edge(CRITICAL, edge, "not_non_first_author", str(position))
    elif etype == "COAUTHORED_WITH":
        for pid in evidence:
            if src not in authors_of.get(pid, {}) or dst not in authors_of.get(pid, {}):
                findings.edge(CRITICAL, edge, "coauthor_not_on_evidence_paper", pid)
                break
        if edge.get("shared_count") != len(edge.get("evidence_paper_ids") or []):
            findings.edge(CRITICAL, edge, "shared_count_mismatch")
    elif etype == "AFFILIATED_WITH":
        for pid in evidence:
            if (pid, src, dst) not in idx["affil"]:
                findings.edge(CRITICAL, edge, "affiliation_row_missing", pid)
                break
            if src not in authors_of.get(pid, {}):
                findings.edge(CRITICAL, edge, "affiliated_author_not_on_paper", pid)
                break
    elif etype == "APPEARS_IN":
        if papers[src].get("venue_id") != dst:
            findings.edge(CRITICAL, edge, "venue_mismatch")
    elif etype == "HAS_TOPIC":
        row = idx["topic_rows"].get((src, dst))
        if row is None:
            findings.edge(CRITICAL, edge, "topic_row_missing")
        else:
            span = (row.get("evidence_span") or "").casefold()
            text = f"{papers[src].get('title') or ''} {papers[src].get('abstract') or ''}".casefold()
            if not span or span not in text:
                findings.edge(CRITICAL, edge, "topic_span_not_in_title_or_abstract")
    elif etype == "CITES":
        if (src, dst) not in idx["cites"]:
            findings.edge(CRITICAL, edge, "citation_row_missing")
        if papers[dst]["year"] > papers[src]["year"]:
            findings.edge(WARNING, edge, "cited_paper_newer_than_citing",
                          f"{papers[src]['year']}->{papers[dst]['year']}")
    elif etype == "ORG_COAUTHORED_WITH":
        for pid in evidence:
            insts = idx["insts_of_paper"].get(pid, set())
            if src not in insts or dst not in insts:
                findings.edge(CRITICAL, edge, "org_pair_not_on_evidence_paper", pid)
                break
    elif etype == "RESEARCHES":
        if len(evidence) < MIN_TOPIC_PAPERS:
            findings.edge(CRITICAL, edge, "below_min_topic_papers")
        for pid in evidence:
            if src not in authors_of.get(pid, {}) or dst not in idx["topics_of"].get(pid, set()):
                findings.edge(CRITICAL, edge, "researches_evidence_invalid", pid)
                break
    elif etype == "ACTIVE_IN":
        if len(evidence) < MIN_TOPIC_PAPERS:
            findings.edge(CRITICAL, edge, "below_min_topic_papers")
        for pid in evidence:
            if src not in idx["insts_of_paper"].get(pid, set()) or dst not in idx["topics_of"].get(pid, set()):
                findings.edge(CRITICAL, edge, "active_in_evidence_invalid", pid)
                break


def audit_edges(edges: dict[str, list[dict[str, Any]]], nodes: dict[str, list[dict[str, Any]]],
                rows: dict[str, list[dict[str, Any]]], findings: Findings) -> dict[str, int]:
    label_of = {record["id"]: label for label, records in nodes.items() for record in records}
    papers = {paper["id"]: paper for paper in rows["papers.jsonl"]}
    idx = _index(rows)
    scanned: dict[str, int] = {}
    for etype in REL_TYPES:
        records = edges.get(etype, [])
        scanned[etype] = len(records)
        seen: set[tuple[str, str]] = set()
        for edge in records:
            key = (edge["from"], edge["to"])
            if key in seen:
                findings.edge(CRITICAL, edge, "duplicate_edge")
            seen.add(key)
            if etype in SYMMETRIC:
                if edge["from"] > edge["to"]:
                    findings.edge(CRITICAL, edge, "symmetric_not_canonical_order")
                if (edge["to"], edge["from"]) in seen and edge["from"] != edge["to"]:
                    findings.edge(CRITICAL, edge, "symmetric_reverse_duplicate")
            if _check_generic(edge, label_of, papers, findings):
                _check_semantics(edge, idx, papers, findings)
    return scanned


def _hash_edges(edges: dict[str, list[dict[str, Any]]]) -> str:
    digest = hashlib.sha256()
    for etype in REL_TYPES:
        for edge in sorted(edges.get(etype, []), key=lambda e: (e["from"], e["to"])):
            digest.update(json.dumps(edge, sort_keys=True, ensure_ascii=False).encode())
    return digest.hexdigest()


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run_integrity(data_dir: Path, out_dir: Path) -> int:
    rows = load_dataset(data_dir)
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    nodes = _node_tables(rows, manifest.get("topic_rule_version", ""))

    rejected_tmp = out_dir / "_rejected_tmp"
    first = derive_edges(rows, rejected_tmp)
    second = derive_edges(rows, rejected_tmp)
    deterministic = _hash_edges(first) == _hash_edges(second)

    on_disk: dict[str, list[dict[str, Any]]] = {}
    derived_matches_disk = True
    for etype in REL_TYPES:
        path = DERIVED / f"edges_{etype}.jsonl"
        on_disk[etype] = read_jsonl(path) if path.exists() else []
    derived_matches_disk = _hash_edges(on_disk) == _hash_edges(first)

    findings = Findings()
    node_scanned = audit_nodes(nodes, findings)
    edge_scanned = audit_edges(first, nodes, rows, findings)

    severity_counts = Counter(item["severity"] for item in findings.node_errors + findings.edge_errors)
    by_check = Counter(
        f"{item.get('type') or item.get('label')}:{item['check']}:{item['severity']}"
        for item in findings.node_errors + findings.edge_errors
    )
    expected_nodes = sum(len(v) for v in nodes.values())
    expected_edges = sum(len(v) for v in first.values())
    report = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "population": "census (100% of nodes and edges in the local snapshot; no sampling)",
        "graph_source": "LOCAL_SNAPSHOT data/processed + re-derived edges (Aura live not reachable in this run)",
        "snapshot_manifest_checksums": manifest.get("checksums"),
        "derived_edges_sha256": _hash_edges(first),
        "derivation_deterministic": deterministic,
        "derived_files_match_fresh_derivation": derived_matches_disk,
        "nodes_scanned": node_scanned,
        "edges_scanned": edge_scanned,
        "total_nodes_scanned": sum(node_scanned.values()),
        "total_edges_scanned": sum(edge_scanned.values()),
        "scanned_equals_population": (
            sum(node_scanned.values()) == expected_nodes and sum(edge_scanned.values()) == expected_edges
        ),
        "relation_types_populated": sum(1 for v in edge_scanned.values() if v > 0),
        "error_counts_by_severity": dict(severity_counts),
        "error_counts_by_check": dict(sorted(by_check.items())),
        "critical_errors": severity_counts.get(CRITICAL, 0),
        "url_reachability": "NOT_RUN (syntax only; no bulk HTTP probing from this laptop)",
        "verdict": "PASS" if severity_counts.get(CRITICAL, 0) == 0 and deterministic else "FAIL",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "integrity_all.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                                                encoding="utf-8")
    _write_csv(out_dir / "node_errors.csv", findings.node_errors, ["severity", "label", "id", "check", "detail"])
    _write_csv(out_dir / "edge_errors.csv", findings.edge_errors,
               ["severity", "type", "from", "to", "check", "detail"])
    for leftover in rejected_tmp.glob("*"):
        leftover.unlink()
    if rejected_tmp.exists():
        rejected_tmp.rmdir()
    print(json.dumps({k: report[k] for k in (
        "total_nodes_scanned", "total_edges_scanned", "relation_types_populated",
        "error_counts_by_severity", "derivation_deterministic", "derived_files_match_fresh_derivation",
        "verdict")}, ensure_ascii=False))
    return 0 if report["verdict"] == "PASS" else 5
