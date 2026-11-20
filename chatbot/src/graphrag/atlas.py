"""Read-only adapter from offline analysis artifacts to the Atlas UI contract."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


class AtlasSnapshotError(RuntimeError):
    """Raised when the real offline snapshot is missing or malformed."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise AtlasSnapshotError(f"cannot read {path.name}: {type(error).__name__}") from error
    if not isinstance(value, dict):
        raise AtlasSnapshotError(f"{path.name} must contain a JSON object")
    return value


def load_atlas_snapshot(data_dir: Path, *, max_nodes: int = 140, max_edges: int = 500) -> dict[str, Any]:
    """Build a bounded interactive network from real, versioned offline outputs."""
    required = {
        "counts": data_dir / "graph_counts.json",
        "network": data_dir / "author_network.json",
        "metrics": data_dir / "author_metrics.csv",
        "edges": data_dir / "author_projection_edges.csv",
        "small_world": data_dir / "small_world.json",
    }
    missing = [path.name for path in required.values() if not path.is_file()]
    if missing:
        raise AtlasSnapshotError(f"missing real analysis artifacts: {', '.join(sorted(missing))}")

    counts = _read_json(required["counts"])
    network = _read_json(required["network"])
    small_world = _read_json(required["small_world"])
    sensitivity_path = data_dir / "small_world_subnetworks.json"
    sensitivity = _read_json(sensitivity_path) if sensitivity_path.is_file() else None

    with open(required["metrics"], encoding="utf-8", newline="") as handle:
        metric_rows = list(csv.DictReader(handle))
    metrics_by_id = {row["author_id"]: row for row in metric_rows}
    ranked = sorted(metric_rows, key=lambda row: (-float(row["pagerank"]), row["author_id"]))
    selected = {row["author_id"] for row in ranked[:60]}

    with open(required["edges"], encoding="utf-8", newline="") as handle:
        edge_rows = list(csv.DictReader(handle))
    # Add neighbours of the highest-ranked authors so the preview has inspectable local structure,
    # while retaining a hard payload bound for the browser.
    anchors = {row["author_id"] for row in ranked[:20]}
    incident = sorted(
        (row for row in edge_rows if row["min_author_id"] in anchors or row["max_author_id"] in anchors),
        key=lambda row: (-int(row["shared_count"]), row["min_author_id"], row["max_author_id"]),
    )
    for row in incident:
        if len(selected) >= max_nodes:
            break
        selected.update((row["min_author_id"], row["max_author_id"]))
    selected = set(
        sorted(selected, key=lambda node_id: (-float(metrics_by_id[node_id]["pagerank"]), node_id))[
            :max_nodes
        ]
    )

    edges = [
        row for row in edge_rows if row["min_author_id"] in selected and row["max_author_id"] in selected
    ]
    edges.sort(key=lambda row: (-int(row["shared_count"]), row["min_author_id"], row["max_author_id"]))
    edges = edges[:max_edges]
    connected_ids = {node for row in edges for node in (row["min_author_id"], row["max_author_id"])}
    # Preserve top PageRank isolates in the bounded view as useful ranked results.
    visible_ids = connected_ids | {row["author_id"] for row in ranked[:20]}

    nodes = []
    for node_id in sorted(visible_ids, key=lambda value: (-float(metrics_by_id[value]["pagerank"]), value)):
        row = metrics_by_id[node_id]
        nodes.append(
            {
                "id": node_id,
                "name": row["name"],
                "identity_status": row["identity_status"],
                "degree": int(row["degree"]),
                "weighted_degree": int(row["weighted_degree"]),
                "pagerank": float(row["pagerank"]),
                "community": int(row["community"]) if row["community"] else None,
                "core_number": int(row["core_number"]),
            }
        )
    graph_edges = [
        {
            "id": f"{row['min_author_id']}::{row['max_author_id']}",
            "source": row["min_author_id"],
            "target": row["max_author_id"],
            "shared_count": int(row["shared_count"]),
            "evidence_paper_ids": [value for value in row["paper_ids"].split("|") if value],
        }
        for row in edges
    ]

    return {
        "schema_version": "atlas-snapshot-v1",
        "source_kind": "real_offline_snapshot",
        "scope_id": "nlpgraph-v1",
        "provenance": {
            "directory": "offline/output/analysis",
            "artifacts": [path.name for path in required.values()]
            + ([sensitivity_path.name] if sensitivity else []),
            "projection": network.get("projection"),
            "analysis_source": network.get("source"),
        },
        "counts": counts,
        "network_stats": network.get("stats", {}),
        "top_pagerank": network.get("top10_pagerank", []),
        "communities": network.get("communities", {}),
        "community_summary": network.get("community_summary", []),
        "core": network.get("core", {}),
        "small_world": small_world,
        "small_world_sensitivity": sensitivity,
        "graph": {"nodes": nodes, "edges": graph_edges, "bounded": True, "max_nodes": max_nodes},
        "caveats": network.get("caveats", []),
    }
