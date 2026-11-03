"""Author-only co-authorship network analysis (NetworkX). Projection uses COAUTHORED_WITH only."""
from __future__ import annotations

import csv
import math
import random
from collections import Counter
from pathlib import Path
from typing import Any

import networkx as nx

SEED = 20261107


def build_projection(authors: list[dict[str, Any]], coauthor_edges: list[dict[str, Any]]) -> nx.Graph:
    g = nx.Graph()
    for a in authors:
        g.add_node(a["id"], name=a["name"], status=a["identity_status"])
    for e in coauthor_edges:
        a, b = e["from"], e["to"]
        if a == b:
            continue
        if g.has_edge(a, b):  # should not happen (canonical pairs) - keep the max evidence
            g[a][b]["paper_ids"] = sorted(set(g[a][b]["paper_ids"]) | set(e["evidence_paper_ids"]))
        else:
            g.add_edge(a, b, paper_ids=list(e["evidence_paper_ids"]))
        g[a][b]["weight"] = len(g[a][b]["paper_ids"])
    return g


def basic_stats(g: nx.Graph) -> dict[str, Any]:
    comps = sorted(nx.connected_components(g), key=len, reverse=True)
    lcc = comps[0] if comps else set()
    n = g.number_of_nodes()
    return {
        "authors_total": n, "edges": g.number_of_edges(), "isolates": nx.number_of_isolates(g),
        "connected_components": len(comps), "lcc_size": len(lcc),
        "lcc_ratio_of_all_authors": round(len(lcc) / n, 4) if n else 0.0,
        "density": round(nx.density(g), 6) if n > 1 else 0.0,
        "component_size_top10": [len(c) for c in comps[:10]],
        "mean_degree": round(2 * g.number_of_edges() / n, 3) if n else 0.0,
    }


def top_by(g: nx.Graph, score: dict[str, float], k: int = 10) -> list[dict[str, Any]]:
    rows = []
    for node, s in sorted(score.items(), key=lambda x: (-x[1], x[0]))[:k]:
        papers = sorted({p for nb in g[node] for p in g[node][nb]["paper_ids"]})
        rows.append({"author_id": node, "name": g.nodes[node].get("name"), "score": round(float(s), 6),
                     "degree": g.degree(node), "weighted_degree": g.degree(node, weight="weight"),
                     "evidence_paper_ids": papers[:5], "n_papers_with_coauthors": len(papers)})
    return rows


def communities(g: nx.Graph, seed: int = SEED) -> dict[str, Any]:
    h = g.subgraph([n for n in g if g.degree(n) > 0]).copy()
    if h.number_of_edges() == 0:
        return {"method": "none", "n_communities": 0, "modularity": None, "communities": []}
    try:
        comms = nx.community.louvain_communities(h, weight="weight", seed=seed)
        method = "louvain (networkx.community.louvain_communities, weight=shared papers)"
    except AttributeError:
        comms = nx.community.greedy_modularity_communities(h, weight="weight")
        method = "greedy_modularity_communities (fallback)"
    comms = sorted((sorted(c) for c in comms), key=lambda c: (-len(c), c[0]))
    mod = nx.community.modularity(h, comms, weight="weight")
    return {"method": method, "seed": seed, "n_communities": len(comms), "modularity": round(mod, 4),
            "nodes_considered": h.number_of_nodes(), "size_top10": [len(c) for c in comms[:10]],
            "communities": comms}


def path_with_evidence(g: nx.Graph, a: str, b: str) -> dict[str, Any] | None:
    try:
        path = nx.shortest_path(g, a, b)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None
    hops = [{"from": u, "from_name": g.nodes[u].get("name"), "to": v, "to_name": g.nodes[v].get("name"),
             "evidence_paper_ids": g[u][v]["paper_ids"]} for u, v in zip(path, path[1:])]
    return {"source": a, "target": b, "length": len(path) - 1, "hops": hops}


def avg_shortest_path(g: nx.Graph, max_exact: int, rng: random.Random, n_sources: int) -> tuple[float, str]:
    n = g.number_of_nodes()
    if n <= max_exact:
        return nx.average_shortest_path_length(g), "exact"
    nodes = sorted(g.nodes())
    srcs = rng.sample(nodes, min(n_sources, n))
    tot, cnt = 0, 0
    for s in srcs:
        d = nx.single_source_shortest_path_length(g, s)
        tot += sum(d.values())
        cnt += len(d) - 1
    return tot / cnt, f"approx: BFS from {len(srcs)} random sources (seeded)"


def small_world(g: nx.Graph, n_random: int = 5, seed: int = SEED, max_exact: int = 3000,
                n_sources: int = 400) -> dict[str, Any]:
    comps = sorted(nx.connected_components(g), key=len, reverse=True)
    if not comps or len(comps[0]) < 10:
        return {"status": "undetermined", "reason": "LCC too small"}
    lcc = nx.Graph(g.subgraph(comps[0]))
    for u, v in lcc.edges():
        lcc[u][v].clear()
    rng = random.Random(seed)
    c_obs = nx.average_clustering(lcc)
    l_obs, l_method = avg_shortest_path(lcc, max_exact, random.Random(seed), n_sources)
    rand = []
    m = lcc.number_of_edges()
    for i in range(n_random):
        r = lcc.copy()
        s = seed + i + 1
        nx.double_edge_swap(r, nswap=10 * m, max_tries=100 * m, seed=s)
        if not nx.is_connected(r):
            r = nx.Graph(r.subgraph(max(nx.connected_components(r), key=len)))
        c_r = nx.average_clustering(r)
        l_r, _ = avg_shortest_path(r, max_exact, random.Random(s), n_sources)
        rand.append({"seed": s, "nodes": r.number_of_nodes(), "C": c_r, "L": l_r})
    c_rand = sum(x["C"] for x in rand) / len(rand)
    l_rand = sum(x["L"] for x in rand) / len(rand)
    sigma = (c_obs / c_rand) / (l_obs / l_rand) if c_rand > 0 and l_rand > 0 else None
    verdict = "undetermined"
    if sigma is not None:
        verdict = ("small-world indication (sigma>1, C>>C_rand, L close to L_rand)"
                   if sigma > 1 and c_obs > 2 * c_rand and l_obs <= 1.5 * l_rand else "no clear small-world indication")
    _ = rng
    return {"status": "computed", "graph": "LCC of author-only co-authorship projection (unweighted)",
            "lcc_nodes": lcc.number_of_nodes(), "lcc_edges": m,
            "C_obs": round(c_obs, 4), "L_obs": round(l_obs, 4), "L_method": l_method,
            "random_model": "degree-preserving double-edge swap (10*m swaps), LCC kept if disconnected",
            "n_random": n_random, "random_graphs": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in x.items()} for x in rand],
            "C_rand": round(c_rand, 4), "L_rand": round(l_rand, 4),
            "sigma": round(sigma, 3) if sigma is not None else None, "verdict": verdict,
            "limitations": ["Multi-author papers create cliques that mechanically raise clustering.",
                            "Sampled corpus (~1k papers) under-represents real collaboration; LCC is fragmented.",
                            "No significance test performed; sigma is descriptive only."]}


def degree_distribution(g: nx.Graph) -> list[tuple[int, int]]:
    return sorted(Counter(d for _, d in g.degree()).items())


def write_pairs_csv(g: nx.Graph, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["min_author_id", "max_author_id", "shared_count", "paper_ids"])
        for u, v, d in sorted((min(u, v), max(u, v), d) for u, v, d in g.edges(data=True)):
            w.writerow([u, v, d["weight"], "|".join(d["paper_ids"])])
