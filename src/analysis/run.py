"""Run the full author-network analysis and write JSON/CSV/PNG outputs."""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any

import networkx as nx

from src.analysis import metrics, visualize
from src.common import DERIVED, log, read_jsonl, write_json
from src.data.contracts import load_dataset
from src.graph.derive import REL_TYPES, derive_edges, write_derived


def _load_edges(rows: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    edges = derive_edges(rows)
    write_derived(edges)
    return edges


def _from_neo4j() -> list[dict[str, Any]]:
    from src.common import SCOPE_ID
    from src.graph.load import connect, database
    drv = connect()
    try:
        with drv.session(database=database()) as s:
            res = s.run("MATCH (a:Author)-[r:COAUTHORED_WITH]->(b:Author) WHERE r.scope_id = $s "
                        "RETURN a.id AS f, b.id AS t, r.evidence_paper_ids AS p", s=SCOPE_ID)
            return [{"from": r["f"], "to": r["t"], "evidence_paper_ids": r["p"]} for r in res]
    finally:
        drv.close()


def run_analysis(data_dir: Path, out: Path, source: str = "local") -> int:
    out.mkdir(parents=True, exist_ok=True)
    rows = load_dataset(data_dir)
    edges = _load_edges(rows)
    co = _from_neo4j() if source == "neo4j" else edges["COAUTHORED_WITH"]
    papers = {p["id"]: p for p in rows["papers.jsonl"]}
    g = metrics.build_projection(rows["authors.jsonl"], co)

    graph_counts = {
        "nodes": {"Paper": len(rows["papers.jsonl"]), "Author": len(rows["authors.jsonl"]),
                  "Institution": len(rows["institutions.jsonl"]), "Venue": len(rows["venues.jsonl"]), "Topic": 6},
        "relationships": {t: len(edges[t]) for t in REL_TYPES},
    }
    graph_counts["total_nodes"] = sum(graph_counts["nodes"].values())
    graph_counts["total_relationships"] = sum(graph_counts["relationships"].values())
    graph_counts["populated_types"] = sum(1 for v in graph_counts["relationships"].values() if v > 0)
    graph_counts["evidence_papers_by_type"] = {t: len({p for e in edges[t] for p in e["evidence_paper_ids"]})
                                               for t in REL_TYPES}
    graph_counts["authors_by_identity_status"] = dict(Counter(a["identity_status"] for a in rows["authors.jsonl"]))
    write_json(out / "graph_counts.json", graph_counts)

    stats = metrics.basic_stats(g)
    deg = dict(g.degree())
    wdeg = dict(g.degree(weight="weight"))
    pr = nx.pagerank(g, weight="weight") if g.number_of_edges() else {}
    comm = metrics.communities(g)
    node_comm = {n: i for i, c in enumerate(comm["communities"]) for n in c}

    # topic profile of the largest communities
    paper_topics: dict[str, list[str]] = {}
    for r in rows["paper_topics.jsonl"]:
        paper_topics.setdefault(r["paper_id"], []).append(r["topic_id"])
    comm_summary = []
    for i, c in enumerate(comm["communities"][:10]):
        cs = set(c)
        pids = {p for u in c for v in g[u] if v in cs for p in g[u][v]["paper_ids"]}
        tc = Counter(t for p in pids for t in paper_topics.get(p, []))
        comm_summary.append({"community": i, "size": len(c), "papers": len(pids),
                             "top_topics": tc.most_common(3),
                             "members_sample": [g.nodes[n]["name"] for n in sorted(c, key=lambda n: -deg[n])[:6]],
                             "paper_examples": [papers[p]["title"] for p in sorted(pids)[:3]]})

    # shortest-path example: between the two highest-PageRank authors in the LCC that are not adjacent
    lcc = max(nx.connected_components(g), key=len) if g.number_of_nodes() else set()
    ranked = [n for n, _ in sorted(pr.items(), key=lambda x: (-x[1], x[0])) if n in lcc]
    path_ex = None
    for a in ranked[:10]:
        for b in ranked[:30]:
            if a != b and not g.has_edge(a, b):
                path_ex = metrics.path_with_evidence(g, a, b)
                if path_ex and path_ex["length"] >= 2:
                    break
        if path_ex and path_ex["length"] >= 2:
            break
    if path_ex:
        for h in path_ex["hops"]:
            h["evidence_titles"] = [papers[p]["title"] for p in h["evidence_paper_ids"]]
            h["evidence_urls"] = [papers[p]["source_url"] for p in h["evidence_paper_ids"]]

    sw = metrics.small_world(g)
    result = {
        "projection": "Author-COAUTHORED_WITH-Author only (undirected, simple, weight = shared papers)",
        "source": source, "stats": stats,
        "top10_degree": metrics.top_by(g, deg), "top10_weighted_degree": metrics.top_by(g, wdeg),
        "top10_pagerank": metrics.top_by(g, pr),
        "communities": {k: v for k, v in comm.items() if k != "communities"}, "community_summary": comm_summary,
        "shortest_path_example": path_ex, "small_world": sw,
        "degree_distribution": metrics.degree_distribution(g),
        "caveats": ["co-authorship != friendship", "PageRank is a structural centrality, not scientific quality",
                    "source_only authors are scoped to one paper and cannot connect across papers"],
    }
    write_json(out / "author_network.json", result)
    write_json(out / "small_world.json", sw)
    metrics.write_pairs_csv(g, out / "author_projection_edges.csv")
    with open(out / "author_metrics.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["author_id", "name", "identity_status", "degree", "weighted_degree", "pagerank", "community"])
        for n in sorted(g.nodes()):
            w.writerow([n, g.nodes[n]["name"], g.nodes[n]["status"], deg[n], wdeg[n], round(pr.get(n, 0), 8),
                        node_comm.get(n, "")])

    visualize.bar(graph_counts["relationships"], "Relationships by type (unique edges)", out / "relationship_types.png")
    visualize.bar(graph_counts["nodes"], "Nodes by label", out / "node_labels.png", color="#4f8a5b")
    visualize.degree_hist(result["degree_distribution"], out / "degree_distribution.png")
    if ranked:
        visualize.subgraph_plot(g, ranked[0], out / "ego_top_pagerank.png", communities=node_comm)
    visualize.small_world_plot(sw, out / "small_world.png")
    log.info("analysis written to %s: %s", out, stats)
    _ = (DERIVED, read_jsonl)
    return 0
