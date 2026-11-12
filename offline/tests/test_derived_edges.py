from src.data.fixtures import fixture_tables, write_dataset
from src.data.contracts import load_dataset
from src.graph import load as loader
from src.graph.derive import REL_TYPES, derive_edges


def _rows(tmp_path):
    write_dataset(tmp_path, fixture_tables())
    return load_dataset(tmp_path)


def edge_set(edges, t):
    return {(e["from"], e["to"]) for e in edges[t]}


def test_all_ten_types_populated_on_fixture(tmp_path):
    e = derive_edges(_rows(tmp_path))
    assert set(e) == set(REL_TYPES)
    assert all(e[t] for t in REL_TYPES), {t: len(e[t]) for t in REL_TYPES}


def test_coauthor_pairs_unique_canonical_with_evidence(tmp_path):
    e = derive_edges(_rows(tmp_path))
    co = e["COAUTHORED_WITH"]
    keys = [(x["from"], x["to"]) for x in co]
    assert len(keys) == len(set(keys))
    assert all(a < b for a, b in keys)
    ab = next(x for x in co if (x["from"], x["to"]) == ("oa:AFIX1", "oa:AFIX2"))
    assert ab["evidence_paper_ids"] == ["oa:WFIX1", "oa:WFIX2"] and ab["shared_count"] == 2


def test_same_name_not_linked_across_papers(tmp_path):
    e = derive_edges(_rows(tmp_path))
    linked = {n for x in e["COAUTHORED_WITH"] for n in (x["from"], x["to"])}
    assert "src:oa:WFIX4#1" not in linked


def test_first_vs_other_author(tmp_path):
    e = derive_edges(_rows(tmp_path))
    assert ("oa:AFIX1", "oa:WFIX1") in edge_set(e, "FIRST_AUTHOR_OF")
    assert ("oa:AFIX1", "oa:WFIX3") in edge_set(e, "OTHER_AUTHOR_OF")
    assert not edge_set(e, "FIRST_AUTHOR_OF") & edge_set(e, "OTHER_AUTHOR_OF")


def test_citation_direction(tmp_path):
    e = derive_edges(_rows(tmp_path))
    assert edge_set(e, "CITES") == {("oa:WFIX2", "oa:WFIX1"), ("oa:WFIX3", "oa:WFIX2")}


def test_researches_threshold(tmp_path):
    e = derive_edges(_rows(tmp_path))
    r = edge_set(e, "RESEARCHES")
    # AFIX1 has llm on W1, W2, W5 -> yes; AFIX4 only W5 -> no
    assert ("oa:AFIX1", "topic:llm") in r
    assert ("oa:AFIX4", "topic:llm") not in r
    assert all(x["evidence_count"] >= 2 for x in e["RESEARCHES"])


def test_active_in_threshold_and_org_pairs(tmp_path):
    e = derive_edges(_rows(tmp_path))
    act = edge_set(e, "ACTIVE_IN")
    assert ("oa:IFIX1", "topic:llm") in act       # W1, W2
    assert ("oa:IFIX2", "topic:mt") not in act    # only W1
    org = e["ORG_COAUTHORED_WITH"]
    assert [(x["from"], x["to"], x["evidence_paper_ids"]) for x in org] == \
        [("oa:IFIX1", "oa:IFIX2", ["oa:WFIX1", "oa:WFIX2", "oa:WFIX3"])]


def test_affiliation_merged_per_pair(tmp_path):
    e = derive_edges(_rows(tmp_path))
    a = next(x for x in e["AFFILIATED_WITH"] if (x["from"], x["to"]) == ("oa:AFIX1", "oa:IFIX1"))
    assert a["evidence_paper_ids"] == ["oa:WFIX1", "oa:WFIX2", "oa:WFIX3"]
    assert a["years"] == [2023, 2024]


def test_large_author_paper_flagged_not_cliqued(tmp_path):
    t = fixture_tables()
    big = [f"oa:ABIG{i:02d}" for i in range(25)]
    t["authors.jsonl"] += [{"id": a, "name": f"Big {i}", "orcid": None, "openalex_id": a[3:], "acl_author_id": None,
                            "identity_status": "verified"} for i, a in enumerate(big)]
    t["paper_authors.jsonl"] = [r for r in t["paper_authors.jsonl"] if r["paper_id"] != "oa:WFIX4"]
    t["paper_authors.jsonl"] += [{"paper_id": "oa:WFIX4", "author_id": a, "position": i,
                                  "author_position": "first" if i == 1 else ("last" if i == 25 else "middle"),
                                  "source_url": "x"} for i, a in enumerate(big, 1)]
    t["authors.jsonl"] = [a for a in t["authors.jsonl"] if a["id"] != "src:oa:WFIX4#1"]
    write_dataset(tmp_path, t)
    e = derive_edges(load_dataset(tmp_path))
    assert not any(x["from"].startswith("oa:ABIG") for x in e["COAUTHORED_WITH"])
    assert len([x for x in e["OTHER_AUTHOR_OF"] if x["to"] == "oa:WFIX4"]) == 24


class FakeTx:
    """Minimal in-memory emulation of the loader's MERGE semantics (keyed by id / (from,type,to))."""

    def __init__(self, db):
        self.db = db

    def run(self, q, rows, scope, build=None):
        n = 0
        if "MERGE (n:" in q:
            lbl = q.split("MERGE (n:")[1].split(" ")[0]
            for r in rows:
                self.db["nodes"].setdefault((lbl, r["id"]), {}).update(r["props"])
                n += 1
        else:
            t = q.split("[r:")[1].split("]")[0]
            fl = q.split("MATCH (a:")[1].split(" ")[0]
            tl = q.split("MATCH (b:")[1].split(" ")[0]
            for r in rows:
                if (fl, r["from"]) in self.db["nodes"] and (tl, r["to"]) in self.db["nodes"]:
                    self.db["rels"].setdefault((r["from"], t, r["to"]), {}).update(r["props"])
                    n += 1

        class R:
            def single(self_inner):
                return {"n": n}
        return R()


def _apply(db, node_rows, edge_rows):
    tx = FakeTx(db)
    for lbl, rs in node_rows.items():
        tx.run(loader._NODE_CYPHER[lbl], rs, "s", "b")
    for t, rs in edge_rows.items():
        tx.run(loader._REL_CYPHER[t], rs, "s")


def test_import_idempotent_with_fake_merge(tmp_path):
    rows = _rows(tmp_path)
    nodes, edges, rejected = loader.build_payload(rows, "topics-v1.0")
    assert rejected == []
    db = {"nodes": {}, "rels": {}}
    _apply(db, nodes, edges)
    n1, r1 = len(db["nodes"]), len(db["rels"])
    _apply(db, nodes, edges)
    assert (len(db["nodes"]), len(db["rels"])) == (n1, r1)
    assert r1 == sum(len(v) for v in edges.values())


def test_cypher_is_whitelisted_merge_only():
    for t, q in loader._REL_CYPHER.items():
        assert t in REL_TYPES and "MERGE" in q and "DELETE" not in q.upper()
    for q in loader._NODE_CYPHER.values():
        assert "MERGE" in q and "DELETE" not in q.upper()


def test_dangling_edges_rejected(tmp_path):
    rows = _rows(tmp_path)
    rows["citations.jsonl"].append({"citing_paper_id": "oa:WFIX1", "cited_paper_id": "oa:WGHOST", "source_url": "x"})
    rows["papers.jsonl"].append({**rows["papers.jsonl"][0], "id": "oa:WGHOST"})
    nodes, edges, rejected = loader.build_payload(rows, "v")
    nodes_ids = {r["id"] for r in nodes["Paper"]}
    assert "oa:WGHOST" in nodes_ids  # present -> not rejected
    rows["papers.jsonl"].pop()
    nodes, edges, rejected = loader.build_payload(rows, "v")
    assert any(r["to"] == "oa:WGHOST" for r in rejected)
