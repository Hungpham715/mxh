"""Cross-source audits that do NOT rely on the data used to build the edge.

* Affiliation: OpenAlex per-authorship institution vs the affiliation string printed in the ACL Anthology XML
  for the same author position (independent source, ACL papers only).
* Identity: verified OpenAlex author ids that occur on >= 2 ACL papers -> do the ACL Anthology author ids agree?
* Identity collisions: same display name mapped to several OpenAlex ids.
* Coverage: missing affiliation / abstract / references, unmatched OpenAlex, duplicate DOI, orphan nodes, UNKNOWN topics.
* 40 random papers: source title / author list / year re-compared with the processed record.
"""
from __future__ import annotations

import csv
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from src.common import EVAL, PROCESSED, RAW, log, read_jsonl, write_json
from src.data.affil import affiliation_agrees
from src.data.contracts import load_dataset
from src.data.normalize import fold
from src.evaluation.score import wilson
from src.graph.derive import derive_edges


def run_audits(seed: int = 20261107, tag: str = "") -> dict[str, Any]:
    rows = load_dataset(PROCESSED)
    papers = {p["id"]: p for p in rows["papers.jsonl"]}
    authors = {a["id"]: a for a in rows["authors.jsonl"]}
    insts = {i["id"]: i for i in rows["institutions.jsonl"]}
    acl_raw = {r["acl_id"]: r for r in read_jsonl(RAW / "acl_selected.jsonl")}
    arx_raw = {r["arxiv_id"]: r for r in read_jsonl(RAW / "arxiv_selected.jsonl")}
    pos = {(r["paper_id"], r["author_id"]): r["position"] for r in rows["paper_authors.jsonl"]}
    res: dict[str, Any] = {}

    def declared(pid: str, aid: str) -> str | None:
        p = papers[pid]
        if p["source_kind"] != "acl":
            return None
        return acl_raw[p["acl_id"]]["authors"][pos[(pid, aid)] - 1].get("raw_affiliation")

    comp, agree, dis = 0, 0, []
    for r in rows["affiliations.jsonl"]:
        d = declared(r["paper_id"], r["author_id"])
        if not d:
            continue
        comp += 1
        if affiliation_agrees(insts[r["institution_id"]]["name"], d):
            agree += 1
        else:
            dis.append({"paper_id": r["paper_id"], "author": authors[r["author_id"]]["name"],
                        "openalex_institution": insts[r["institution_id"]]["name"], "acl_affiliation": d})
    lo, hi = wilson(agree, comp)
    res["affiliation_rows_comparable_with_acl_xml"] = comp
    res["affiliation_row_agreement_with_acl_xml"] = f"{agree}/{comp} = {agree / max(comp, 1):.3f} (Wilson95 {lo:.3f}-{hi:.3f})"
    write_csv(EVAL / f"affiliation_disagreements{tag}.csv", dis)

    edges = derive_edges(rows)
    e_comp = e_ok = 0
    for e in edges["AFFILIATED_WITH"]:
        verdicts = [affiliation_agrees(insts[e["to"]]["name"], d) for pid in e["evidence_paper_ids"]
                    if (d := declared(pid, e["from"]))]
        if verdicts:
            e_comp += 1
            e_ok += any(verdicts)
    lo, hi = wilson(e_ok, e_comp)
    res["AFFILIATED_WITH_edges_agreeing_with_acl_xml"] = f"{e_ok}/{e_comp} = {e_ok / max(e_comp, 1):.3f} (Wilson95 {lo:.3f}-{hi:.3f})"
    res["affiliation_agreement_note"] = ("string agreement is a LOWER bound: OpenAlex often adds a second institution "
                                         "(e.g. parent company, joint lab) that ACL authors did not print; see disagreement CSV")

    acl_ids: dict[str, set[str]] = defaultdict(set)
    multi: Counter[str] = Counter()
    for (pid, aid), p_ in pos.items():
        a, p = authors[aid], papers[pid]
        if a["identity_status"] != "verified" or p["source_kind"] != "acl":
            continue
        multi[aid] += 1
        src = acl_raw[p["acl_id"]]["authors"][p_ - 1]
        if src.get("acl_author_id"):
            acl_ids[aid].add(src["acl_author_id"])
    checked = [a for a in multi if multi[a] >= 2 and a in acl_ids]
    conflicts = [{"author_id": a, "name": authors[a]["name"], "acl_author_ids": sorted(acl_ids[a])}
                 for a in checked if len(acl_ids[a]) > 1]
    res["identity_multi_paper_authors_with_acl_ids"] = len(checked)
    res["identity_acl_id_conflicts"] = len(conflicts)
    by_name: dict[str, set[str]] = defaultdict(set)
    for a in authors.values():
        if a["identity_status"] == "verified":
            by_name[fold(a["name"])].add(a["id"])
    same = {n: sorted(v) for n, v in by_name.items() if len(v) > 1}
    res["same_name_multiple_openalex_ids (kept separate, not merged)"] = len(same)
    amb = [{"kind": "same_name_multiple_ids", "name": n, "ids": "|".join(v)} for n, v in sorted(same.items())[:20]]
    amb += [{"kind": "acl_author_id_conflict", "name": c["name"], "ids": c["author_id"] + " acl:" + "|".join(c["acl_author_ids"])}
            for c in conflicts[:20]]
    write_csv(EVAL / "identity_ambiguous.csv", amb)

    pa_ver = [k for k in pos if authors[k[1]]["identity_status"] == "verified"]
    with_aff = {(r["paper_id"], r["author_id"]) for r in rows["affiliations.jsonl"]}
    res["verified_authorships_missing_institution"] = f"{sum(1 for k in pa_ver if k not in with_aff)}/{len(pa_ver)}"
    res["papers_missing_abstract"] = sum(1 for p in papers.values() if not p["abstract"])
    m = read_jsonl(RAW / "openalex_works.jsonl")
    res["papers_with_openalex_references"] = sum(1 for r in m if r["openalex"] and r["openalex"].get("referenced_works"))
    res["openalex_unmatched_papers"] = sum(1 for p in papers.values() if not p["openalex_id"])
    dois = Counter(p["doi"] for p in papers.values() if p["doi"])
    res["duplicate_doi"] = sum(1 for v in dois.values() if v > 1)
    linked = {e["from"] for t in edges.values() for e in t} | {e["to"] for t in edges.values() for e in t}
    res["orphan_nodes"] = sum(1 for i in list(papers) + list(authors) + list(insts) if i not in linked)
    topic_papers = {r["paper_id"] for r in rows["paper_topics.jsonl"]}
    res["topic_UNKNOWN_rate"] = f"{(len(papers) - len(topic_papers)) / len(papers):.3f}"
    total_refs = sum(len(r["openalex"].get("referenced_works") or []) for r in m if r["openalex"])
    res["citation_endpoint_coverage"] = f"{len(rows['citations.jsonl'])} in-corpus citations out of {total_refs} referenced works"

    rnd = random.Random(seed)
    sample = rnd.sample(sorted(papers), 40)
    ok, detail = 0, []
    by_paper: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for (pid, aid), p_ in pos.items():
        by_paper[pid].append((p_, aid))
    for pid in sample:
        p = papers[pid]
        src = acl_raw.get(p["acl_id"]) if p["source_kind"] == "acl" else arx_raw.get(p["arxiv_id"])
        assert src is not None
        names_src = [a["name"] for a in src["authors"]]
        names_out = [authors[a]["name"] for _, a in sorted(by_paper[pid])]
        good = src["title"] == p["title"] and names_src == names_out and p["year"] == src["year"]
        ok += good
        detail.append({"paper_id": pid, "source_url": p["source_url"], "title_match": src["title"] == p["title"],
                       "author_list_match": names_src == names_out, "year_match": p["year"] == src["year"]})
    write_csv(EVAL / "paper_source_audit_40.csv", detail)
    res["paper_source_audit_40"] = f"{ok}/40 papers: title, ordered author list and year identical to raw source"
    write_json(EVAL / f"source_audits{tag}.json", res)
    for k, v in res.items():
        log.info("audit %s: %s", k, v)
    return res


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        if not rows:
            return
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    import sys

    from src.common import setup_logging
    setup_logging()
    run_audits(tag=sys.argv[1] if len(sys.argv) > 1 else "")
