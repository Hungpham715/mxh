"""Topology projection for the complete heterogeneous knowledge graph."""
from __future__ import annotations

from typing import Any

import networkx as nx

from src.graph.derive import REL_TYPES, TOPICS

NODE_FILES = {
    "papers.jsonl": "Paper",
    "authors.jsonl": "Author",
    "institutions.jsonl": "Institution",
    "venues.jsonl": "Venue",
}


def build_projection(
    rows: dict[str, list[dict[str, Any]]],
    edges: dict[str, list[dict[str, Any]]],
) -> nx.Graph:
    """Return a simple undirected projection of all five node and ten edge types.

    The Neo4j graph remains directed and typed.  This projection intentionally collapses
    direction and parallel relationship types because clustering and shortest-path
    small-world statistics are defined here on simple topology.
    """
    graph = nx.Graph()
    for filename, label in NODE_FILES.items():
        for row in rows[filename]:
            graph.add_node(row["id"], label=label)
    for topic_id in TOPICS:
        graph.add_node(f"topic:{topic_id}", label="Topic")

    for relation_type in REL_TYPES:
        for edge in edges[relation_type]:
            source, target = edge["from"], edge["to"]
            if source == target:
                continue
            missing = [node for node in (source, target) if node not in graph]
            if missing:
                raise ValueError(
                    f"{relation_type} references missing projection nodes: {missing}"
                )
            if graph.has_edge(source, target):
                graph[source][target]["relationship_types"].add(relation_type)
            else:
                graph.add_edge(
                    source,
                    target,
                    relationship_types={relation_type},
                )
    return graph


def analyze(
    rows: dict[str, list[dict[str, Any]]],
    edges: dict[str, list[dict[str, Any]]],
    *,
    n_random: int = 30,
) -> dict[str, Any]:
    """Measure full-KG topology without replacing the author-network analysis."""
    from src.analysis import metrics

    graph = build_projection(rows, edges)
    result = metrics.small_world(
        graph,
        n_random=n_random,
        max_exact=3000,
        n_sources=400,
        graph_description=(
            "LCC of full heterogeneous KG projected as a simple undirected graph "
            "(5 node labels, 10 relationship types)"
        ),
        limitations=[
            "This is a heterogeneous knowledge-graph projection, not a social network of authors.",
            "Authorship and paper membership create dense local motifs that raise clustering.",
            "Direction and parallel relationship types are collapsed for simple-graph topology.",
            "The finite seeded null ensemble gives an empirical clustering tail probability, not a universal proof.",
        ],
    )
    result.update({
        "schema_version": "knowledge-graph-small-world-v1",
        "projection": (
            "All Paper, Author, Institution, Venue and Topic nodes; all ten base "
            "relationship types; direction and parallel types collapsed"
        ),
        "node_labels": {
            label: sum(1 for _, data in graph.nodes(data=True) if data["label"] == label)
            for label in ("Paper", "Author", "Institution", "Venue", "Topic")
        },
        "relationship_types": list(REL_TYPES),
        "simple_edges": graph.number_of_edges(),
        "connected_components": nx.number_connected_components(graph),
        "lcc_ratio": round(
            len(max(nx.connected_components(graph), key=len)) / graph.number_of_nodes(), 4
        ) if graph.number_of_nodes() else 0.0,
    })
    return result
