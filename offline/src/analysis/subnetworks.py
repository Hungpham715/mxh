"""Fragmentation and small-world sensitivity analysis for corpus-defined subnetworks.

The primary ``small_world.json`` remains the whole author projection result.  This module
adds an explicit sensitivity artifact across year, venue, and topic slices so the project
does not over-claim small-world structure from one fragmented sampled corpus.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from collections.abc import Iterable
from itertools import combinations
from pathlib import Path
from typing import Any

import networkx as nx

from src.analysis import metrics
from src.common import write_json


def _projection_for_papers(
    paper_ids: Iterable[str],
    paper_authors: dict[str, list[str]],
    authors: dict[str, dict[str, Any]],
) -> nx.Graph:
    """Build the author projection induced only by the supplied papers."""
    graph = nx.Graph()
    for paper_id in sorted(set(paper_ids)):
        members = sorted(set(paper_authors.get(paper_id, [])))
        for author_id in members:
            author = authors.get(author_id, {})
            graph.add_node(
                author_id,
                name=author.get("name", author_id),
                status=author.get("identity_status", "unknown"),
            )
        for left, right in combinations(members, 2):
            if graph.has_edge(left, right):
                graph[left][right]["paper_ids"].append(paper_id)
            else:
                graph.add_edge(left, right, paper_ids=[paper_id])
    for left, right in graph.edges:
        graph[left][right]["paper_ids"] = sorted(set(graph[left][right]["paper_ids"]))
        graph[left][right]["weight"] = len(graph[left][right]["paper_ids"])
    return graph


def _slice_record(
    dimension: str,
    key: str,
    label: str,
    paper_ids: set[str],
    paper_authors: dict[str, list[str]],
    authors: dict[str, dict[str, Any]],
    *,
    n_random: int,
) -> dict[str, Any]:
    graph = _projection_for_papers(paper_ids, paper_authors, authors)
    stats = metrics.basic_stats(graph)
    sw = metrics.small_world(graph, n_random=n_random, max_exact=1500, n_sources=250)
    return {
        "dimension": dimension,
        "key": key,
        "label": label,
        "papers": len(paper_ids),
        "authors": graph.number_of_nodes(),
        "stats": stats,
        "small_world": sw,
    }


def analyze_subnetworks(
    rows: dict[str, list[dict[str, Any]]],
    whole_graph: nx.Graph,
    *,
    n_random: int = 3,
    min_papers: int = 10,
    whole_distance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare whole-network fragmentation with year, venue, and topic slices."""
    authors = {row["id"]: row for row in rows["authors.jsonl"]}
    papers = {row["id"]: row for row in rows["papers.jsonl"]}
    venues = {row["id"]: row for row in rows["venues.jsonl"]}
    paper_authors: dict[str, list[str]] = defaultdict(list)
    for row in rows["paper_authors.jsonl"]:
        paper_authors[row["paper_id"]].append(row["author_id"])

    slices: list[tuple[str, str, str, set[str]]] = []
    by_year: dict[str, set[str]] = defaultdict(set)
    by_venue: dict[str, set[str]] = defaultdict(set)
    by_topic: dict[str, set[str]] = defaultdict(set)
    for paper_id, paper in papers.items():
        by_year[str(paper["year"])].add(paper_id)
        by_venue[paper["venue_id"]].add(paper_id)
    for row in rows["paper_topics.jsonl"]:
        by_topic[row["topic_id"]].add(row["paper_id"])

    for key, ids in sorted(by_year.items()):
        slices.append(("year", key, key, ids))
    for key, ids in sorted(by_venue.items()):
        venue = venues.get(key, {})
        label = venue.get("name", key)
        slices.append(("venue", key, label, ids))
    for key, ids in sorted(by_topic.items()):
        slices.append(("topic", key, key, ids))

    records = [
        _slice_record(dim, key, label, ids, paper_authors, authors, n_random=n_random)
        for dim, key, label, ids in slices
        if len(ids) >= min_papers
    ]
    whole = metrics.basic_stats(whole_graph)
    verdict_counts: dict[str, int] = defaultdict(int)
    for record in records:
        verdict_counts[record["small_world"].get("verdict", record["small_world"]["status"])] += 1
    indication = [
        f"{r['dimension']}:{r['key']}"
        for r in records
        if str(r["small_world"].get("verdict", "")).startswith("small-world indication")
    ]
    conclusion = (
        "The sampled author graph is strongly fragmented; slice-level results are sensitivity "
        "checks, not evidence for the unsampled global collaboration network."
    )
    return {
        "schema_version": "small-world-sensitivity-v1",
        "method": {
            "projection": "undirected author co-authorship induced by papers in each slice",
            "slices": ["year", "venue", "topic"],
            "minimum_papers_per_slice": min_papers,
            "random_model": "degree-preserving double-edge swap on each slice LCC",
            "n_random_per_slice": n_random,
            "formula": "sigma = (C_obs / C_rand) / (L_obs / L_rand)",
            "decision_rule": "indication only when sigma>1, C_obs>2*C_rand, and L_obs<=1.5*L_rand",
        },
        "whole_network_fragmentation": {
            **whole,
            "distance": whole_distance if whole_distance is not None else metrics.whole_network_distance(whole_graph),
            "authors_outside_lcc": whole["authors_total"] - whole["lcc_size"],
            "authors_outside_lcc_ratio": round(1 - whole["lcc_ratio_of_all_authors"], 4),
            "interpretation": (
                "Corpus sampling and source-only identities split the observed projection "
                "into many components."
            ),
        },
        "slice_count": len(records),
        "verdict_counts": dict(sorted(verdict_counts.items())),
        "slices_with_small_world_indication": indication,
        "conclusion": conclusion,
        "slices": records,
    }


def write_subnetwork_outputs(result: dict[str, Any], json_path: Path, csv_path: Path) -> None:
    write_json(json_path, result)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "dimension",
                "key",
                "label",
                "papers",
                "authors",
                "edges",
                "components",
                "lcc_size",
                "lcc_ratio",
                "C_obs",
                "L_obs",
                "C_rand",
                "L_rand",
                "sigma",
                "verdict",
            ]
        )
        for record in result["slices"]:
            stats = record["stats"]
            sw = record["small_world"]
            writer.writerow(
                [
                    record["dimension"],
                    record["key"],
                    record["label"],
                    record["papers"],
                    record["authors"],
                    stats["edges"],
                    stats["connected_components"],
                    stats["lcc_size"],
                    stats["lcc_ratio_of_all_authors"],
                    sw.get("C_obs"),
                    sw.get("L_obs"),
                    sw.get("C_rand"),
                    sw.get("L_rand"),
                    sw.get("sigma"),
                    sw.get("verdict", sw.get("status")),
                ]
            )
