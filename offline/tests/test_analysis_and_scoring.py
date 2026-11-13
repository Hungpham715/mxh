import networkx as nx

from src.analysis import metrics
from src.evaluation.score import score_rows, wilson


def _g():
    authors = [{"id": f"a{i}", "name": f"A{i}", "identity_status": "verified"} for i in range(8)]
    edges = [("a0", "a1", ["p1"]), ("a1", "a2", ["p1", "p2"]), ("a0", "a2", ["p1"]), ("a2", "a3", ["p3"]),
             ("a5", "a6", ["p4"])]
    return metrics.build_projection(authors, [{"from": a, "to": b, "evidence_paper_ids": p} for a, b, p in edges])


def test_projection_and_stats_disconnected():
    g = _g()
    s = metrics.basic_stats(g)
    assert s["authors_total"] == 8 and s["edges"] == 5
    assert s["isolates"] == 2 and s["connected_components"] == 4 and s["lcc_size"] == 4
    assert g["a1"]["a2"]["weight"] == 2


def test_path_evidence():
    g = _g()
    p = metrics.path_with_evidence(g, "a0", "a3")
    assert p["length"] == 2 and p["hops"][-1]["evidence_paper_ids"] == ["p3"]
    assert metrics.path_with_evidence(g, "a0", "a5") is None


def test_communities_deterministic():
    g = _g()
    c1, c2 = metrics.communities(g), metrics.communities(g)
    assert c1["communities"] == c2["communities"] and c1["n_communities"] >= 2


def test_small_world_runs_on_toy():
    g = nx.connected_watts_strogatz_graph(60, 6, 0.1, seed=1)
    g = nx.relabel_nodes(g, {n: f"n{n}" for n in g})
    for n in g:
        g.nodes[n]["name"] = n
    for u, v in g.edges():
        g[u][v]["paper_ids"] = ["p"]
        g[u][v]["weight"] = 1
    sw = metrics.small_world(g, n_random=5)
    assert sw["status"] == "computed" and sw["sigma"] > 1
    assert sw["C_obs"] > sw["C_rand"]


def test_small_world_undetermined_on_tiny():
    assert metrics.small_world(_g())["status"] == "undetermined"


def test_wilson():
    lo, hi = wilson(19, 20)
    # reliable-kg-estimation Wilson: near-ceiling counts use an exact chi-square upper bound.
    assert round(lo, 3) == 0.764 and round(hi, 3) == 0.997
    assert wilson(0, 0) == (0.0, 0.0)


def test_weighted_micro_not_raw_ratio():
    rows = ([{"type": "CITES", "label": "correct", "graph_count_type": 900}] * 20 +
            [{"type": "APPEARS_IN", "label": "correct", "graph_count_type": 100}] * 10 +
            [{"type": "APPEARS_IN", "label": "incorrect", "error_reason": "derivation", "graph_count_type": 100}] * 10)
    s = score_rows(rows)
    assert s["per_type"]["APPEARS_IN"]["precision"] == 0.5
    assert s["micro_precision_weighted"] == 0.95          # 0.9*1 + 0.1*0.5
    assert abs(30 / 40 - s["micro_precision_weighted"]) > 0.1


def test_unverifiable_counts_as_not_correct():
    rows = [{"type": "CITES", "label": "correct", "graph_count_type": 10}] * 9 + \
           [{"type": "CITES", "label": "unverifiable", "graph_count_type": 10}]
    s = score_rows(rows)["per_type"]["CITES"]
    assert s["precision"] == 0.9 and s["unverifiable"] == 1 and s["precision_excluding_unverifiable"] == 1.0
