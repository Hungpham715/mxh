import networkx as nx

from src.analysis import metrics, subnetworks
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


def test_core_decomposition_finds_triangle_kernel():
    g = _g()
    core = metrics.core_decomposition(g)
    assert core["max_core"] == 2 and core["kernel_size"] == 3
    assert {m["author_id"] for m in core["kernel_members"]} == {"a0", "a1", "a2"}
    assert core["community_kernels"] == []


def test_core_decomposition_community_kernels_and_empty_graph():
    g = _g()
    core = metrics.core_decomposition(g, [["a0", "a1", "a2", "a3"], ["a5", "a6"]])
    assert core["community_kernels"][0]["max_core"] == 2
    assert core["community_kernels"][1]["max_core"] == 1
    assert core["community_kernels"][0]["kernel_members"][0] in {"A0", "A1", "A2"}
    empty = metrics.core_decomposition(nx.Graph())
    assert empty["max_core"] == 0 and empty["kernel_members"] == []


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
    sw = metrics.small_world(_g())
    assert sw["status"] == "undetermined"
    assert sw["whole_network_distance"]["reachable_pair_fraction"] < 1
    assert sw["whole_network_distance"]["global_efficiency"] > 0


def test_whole_network_distance_handles_disconnected_pairs():
    g = nx.path_graph(3)
    g.add_node(3)
    profile = metrics.whole_network_distance(g)
    assert profile["reachable_pair_fraction"] == 0.5
    assert profile["component_weighted_average_shortest_path"] == 1.3333
    assert profile["harmonic_path_length_reachable"] == 1.2
    assert profile["global_efficiency"] == 0.416667


def test_subnetwork_sensitivity_uses_corpus_slices():
    authors = [{"id": f"a{i}", "name": f"A{i}", "identity_status": "verified"} for i in range(4)]
    rows = {
        "authors.jsonl": authors,
        "papers.jsonl": [
            {"id": "p1", "year": 2024, "venue_id": "v1"},
            {"id": "p2", "year": 2025, "venue_id": "v1"},
        ],
        "venues.jsonl": [{"id": "v1", "name": "Venue One"}],
        "paper_authors.jsonl": [
            {"paper_id": "p1", "author_id": "a0"}, {"paper_id": "p1", "author_id": "a1"},
            {"paper_id": "p2", "author_id": "a1"}, {"paper_id": "p2", "author_id": "a2"},
        ],
        "paper_topics.jsonl": [
            {"paper_id": "p1", "topic_id": "qa"}, {"paper_id": "p2", "topic_id": "qa"},
        ],
    }
    result = subnetworks.analyze_subnetworks(rows, _g(), n_random=1, min_papers=1)
    assert result["schema_version"] == "small-world-sensitivity-v1"
    assert result["whole_network_fragmentation"]["authors_outside_lcc"] == 4
    assert {(row["dimension"], row["key"]) for row in result["slices"]} == {
        ("year", "2024"), ("year", "2025"), ("venue", "v1"), ("topic", "qa")
    }
    venue = next(row for row in result["slices"] if row["dimension"] == "venue")
    assert venue["papers"] == 2 and venue["stats"]["edges"] == 2


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
