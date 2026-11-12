"""Derive the 10 relationship types (with provenance) from the validated JSONL snapshot.

The same derived edge files feed both the Neo4j loader and the local analysis, so counts agree.
"""
from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import Any

from src.common import BUILD_VERSION, DERIVED, REJECTED, log, write_jsonl

REL_TYPES = (
    "FIRST_AUTHOR_OF", "OTHER_AUTHOR_OF", "COAUTHORED_WITH", "AFFILIATED_WITH", "APPEARS_IN",
    "HAS_TOPIC", "CITES", "ORG_COAUTHORED_WITH", "RESEARCHES", "ACTIVE_IN",
)
# relationship -> (from label, to label, undirected?)
REL_SCHEMA = {
    "FIRST_AUTHOR_OF": ("Author", "Paper", False),
    "OTHER_AUTHOR_OF": ("Author", "Paper", False),
    "COAUTHORED_WITH": ("Author", "Author", True),
    "AFFILIATED_WITH": ("Author", "Institution", False),
    "APPEARS_IN": ("Paper", "Venue", False),
    "HAS_TOPIC": ("Paper", "Topic", False),
    "CITES": ("Paper", "Paper", False),
    "ORG_COAUTHORED_WITH": ("Institution", "Institution", True),
    "RESEARCHES": ("Author", "Topic", False),
    "ACTIVE_IN": ("Institution", "Topic", False),
}
MAX_CLIQUE_AUTHORS = 20
MIN_TOPIC_PAPERS = 2

TOPICS = {
    "llm": ("Large language models", "Large language models, instruction tuning, alignment of LMs"),
    "mt": ("Machine translation", "Machine / neural translation and translation quality"),
    "qa": ("Question answering", "Question answering and machine reading comprehension"),
    "retrieval": ("Retrieval and RAG", "Information retrieval, dense retrieval, retrieval-augmented generation"),
    "summarization": ("Summarization", "Text / document summarization"),
    "safety_eval": ("Safety and LLM evaluation", "LM safety, LLM evaluation, hallucination, red teaming"),
}


def topic_nodes(rule_version: str) -> list[dict[str, Any]]:
    return [{"id": f"topic:{t}", "topic_key": t, "name": n, "description": d, "rule_version": rule_version}
            for t, (n, d) in TOPICS.items()]


def _edge(rtype: str, src: str, dst: str, source_kind: str, paper_ids: list[str], years: list[int],
          source_url: str | None = None, **extra: Any) -> dict[str, Any]:
    pids = sorted(set(paper_ids))
    ys = sorted(set(y for y in years if y is not None))
    e = {"type": rtype, "from": src, "to": dst, "source_kind": source_kind,
         "source_url": source_url, "evidence_paper_ids": pids, "evidence_count": len(pids),
         "first_year": ys[0] if ys else None, "last_year": ys[-1] if ys else None, "years": ys,
         "build_version": BUILD_VERSION}
    e.update(extra)
    return e


def derive_edges(rows: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    papers = {p["id"]: p for p in rows["papers.jsonl"]}
    authors = {a["id"]: a for a in rows["authors.jsonl"]}
    edges: dict[str, list[dict[str, Any]]] = {t: [] for t in REL_TYPES}
    flagged: list[dict[str, Any]] = []

    by_paper: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pa in rows["paper_authors.jsonl"]:
        p = papers[pa["paper_id"]]
        by_paper[pa["paper_id"]].append(pa)
        rtype = "FIRST_AUTHOR_OF" if pa["position"] == 1 else "OTHER_AUTHOR_OF"
        edges[rtype].append(_edge(rtype, pa["author_id"], pa["paper_id"], p["source_kind"], [p["id"]], [p["year"]],
                                  pa["source_url"], position=pa["position"], author_position=pa["author_position"]))

    # 3. COAUTHORED_WITH -- canonical unordered pair (min_id, max_id)
    co: dict[tuple[str, str], list[str]] = defaultdict(list)
    for pid, pas in by_paper.items():
        ids = sorted({pa["author_id"] for pa in pas})
        if len(ids) > MAX_CLIQUE_AUTHORS:
            flagged.append({"paper_id": pid, "n_authors": len(ids), "reason": f">{MAX_CLIQUE_AUTHORS} authors: clique held for manual review"})
            continue
        for a, b in combinations(ids, 2):
            co[(a, b)].append(pid)
    for (a, b), pids in sorted(co.items()):
        edges["COAUTHORED_WITH"].append(_edge("COAUTHORED_WITH", a, b, "derived", pids,
                                              [papers[p]["year"] for p in pids], None, shared_count=len(set(pids))))

    # 4. AFFILIATED_WITH -- per (author, institution), evidence = papers whose authorship declares it
    aff: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows["affiliations.jsonl"]:
        aff[(r["author_id"], r["institution_id"])].append(r)
    for (a, i), rs in sorted(aff.items()):
        pids = [r["paper_id"] for r in rs]
        edges["AFFILIATED_WITH"].append(_edge("AFFILIATED_WITH", a, i, "openalex", pids, [r["year"] for r in rs],
                                              rs[0]["source_url"]))

    # 5. APPEARS_IN
    for p in sorted(papers.values(), key=lambda r: r["id"]):
        edges["APPEARS_IN"].append(_edge("APPEARS_IN", p["id"], p["venue_id"], p["source_kind"], [p["id"]],
                                         [p["year"]], p["source_url"]))

    # 6. HAS_TOPIC
    paper_topics: dict[str, set[str]] = defaultdict(set)
    for r in rows["paper_topics.jsonl"]:
        p = papers[r["paper_id"]]
        paper_topics[r["paper_id"]].add(r["topic_id"])
        edges["HAS_TOPIC"].append(_edge("HAS_TOPIC", r["paper_id"], f"topic:{r['topic_id']}", "derived", [p["id"]],
                                        [p["year"]], p["source_url"], rule_id=r["rule_id"],
                                        evidence_span=r["evidence_span"], confidence_band=r["confidence_band"]))

    # 7. CITES
    for r in rows["citations.jsonl"]:
        edges["CITES"].append(_edge("CITES", r["citing_paper_id"], r["cited_paper_id"], "openalex",
                                    [r["citing_paper_id"]], [papers[r["citing_paper_id"]]["year"]], r["source_url"]))

    # 8. ORG_COAUTHORED_WITH -- institutions declared by two DIFFERENT authors of the same paper
    inst_by_paper_author: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for r in rows["affiliations.jsonl"]:
        inst_by_paper_author[r["paper_id"]][r["author_id"]].add(r["institution_id"])
    org: dict[tuple[str, str], list[str]] = defaultdict(list)
    for pid, amap in inst_by_paper_author.items():
        pairs: set[tuple[str, str]] = set()
        for a1, a2 in combinations(sorted(amap), 2):
            for i in amap[a1]:
                for j in amap[a2]:
                    if i != j:
                        pairs.add((min(i, j), max(i, j)))
        for pr in pairs:
            org[pr].append(pid)
    for (i, j), pids in sorted(org.items()):
        edges["ORG_COAUTHORED_WITH"].append(_edge("ORG_COAUTHORED_WITH", i, j, "derived", pids,
                                                  [papers[p]["year"] for p in pids], None, shared_count=len(set(pids))))

    # 9. RESEARCHES -- author with >= 2 distinct corpus papers in the topic
    at: dict[tuple[str, str], set[str]] = defaultdict(set)
    for pid, pas in by_paper.items():
        for pa in pas:
            for t in paper_topics.get(pid, ()):
                at[(pa["author_id"], t)].add(pid)
    for (a, t), pids in sorted(at.items()):
        if len(pids) >= MIN_TOPIC_PAPERS:
            edges["RESEARCHES"].append(_edge("RESEARCHES", a, f"topic:{t}", "derived", list(pids),
                                             [papers[p]["year"] for p in pids]))

    # 10. ACTIVE_IN -- institution with >= 2 distinct corpus papers in the topic
    it: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in rows["affiliations.jsonl"]:
        for t in paper_topics.get(r["paper_id"], ()):
            it[(r["institution_id"], t)].add(r["paper_id"])
    for (i, t), pids in sorted(it.items()):
        if len(pids) >= MIN_TOPIC_PAPERS:
            edges["ACTIVE_IN"].append(_edge("ACTIVE_IN", i, f"topic:{t}", "derived", list(pids),
                                            [papers[p]["year"] for p in pids]))

    for t in REL_TYPES:
        for e in edges[t]:
            if e["source_url"] is None:
                e["source_url"] = papers[e["evidence_paper_ids"][0]]["source_url"]
    _ = authors
    write_jsonl(REJECTED / "large_author_papers.jsonl", flagged)
    return edges


def write_derived(edges: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    counts = {}
    for t, es in edges.items():
        counts[t] = write_jsonl(DERIVED / f"edges_{t}.jsonl", es)
    log.info("derived edges: %s (total %d)", counts, sum(counts.values()))
    return counts
