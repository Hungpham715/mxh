"""Two-round stratified sample for MANUAL review of AFFILIATED_WITH, ORG_COAUTHORED_WITH, ACTIVE_IN.

* Reads the 3 relationship types from Neo4j AuraDB with a READ-ONLY session (default_access_mode=READ,
  execute_read). Nothing is written to the database.
* Cross-checks the AuraDB edge set against the local snapshot (data/processed + derived edges); aborts on mismatch.
* Stratifies by institution-frequency tier x source-confidence (whether an ACL-printed affiliation backs the edge),
  proportional allocation, fixed seed. Round 1 = 50 per type; round 2 = 50 more per type, disjoint, reserved in
  evaluation/sampling/ and NOT placed in any reviewer sheet.
* Reviewer sheets contain only source metadata (titles, links, author positions, affiliation strings as printed in
  the source metadata). No automated labels, no confidence/stratum fields.

Run:  uv run python -m src.evaluation.manual_sample
"""
from __future__ import annotations

import csv
import hashlib
import random
import subprocess
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from src.common import EVAL, PROCESSED, RAW, ROOT, SCOPE_ID, load_env, log, read_json, read_jsonl, setup_logging, write_json
from src.data.contracts import load_dataset
from src.data.normalize import short_oa
from src.graph.derive import derive_edges

TYPES = ("AFFILIATED_WITH", "ORG_COAUTHORED_WITH", "ACTIVE_IN")
SEED = 20261107
PER_ROUND = 50
OVERLAP_PER_TYPE = 10
SAMPLING = EVAL / "sampling"

SHEET_COLUMNS = [
    "review_id", "round", "is_overlap", "edge_type", "source_id", "source_name", "target_id", "target_name",
    "paper_id", "paper_title", "paper_url", "pdf_url", "year", "n_supporting_papers", "supporting_papers",
    "evidence_text", "label", "error_type", "reviewer", "note", "adjudicated_label",
]
LABEL_COLUMNS = ("label", "error_type", "reviewer", "note", "adjudicated_label")

TOPIC_VI = {"llm": "Large language models", "mt": "Machine translation", "qa": "Question answering",
            "retrieval": "Retrieval / RAG", "summarization": "Summarization", "safety_eval": "Safety & LLM evaluation"}


# --------------------------------------------------------------------------------------------- AuraDB (READ only)
def read_edges_from_aura() -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    from neo4j import READ_ACCESS

    from src.graph.load import LABELS, connect, database
    from src.graph.derive import REL_TYPES

    drv = connect()
    try:
        with drv.session(database=database(), default_access_mode=READ_ACCESS) as s:
            def q(tx, cypher, **p):
                return [r.data() for r in tx.run(cypher, **p)]

            edges: dict[str, list[dict[str, Any]]] = {}
            for t in TYPES:  # t comes from the fixed whitelist above, never from input
                edges[t] = s.execute_read(q, f"MATCH (a)-[r:{t}]->(b) WHERE r.scope_id = $s "
                                             "RETURN a.id AS src, b.id AS dst, r.evidence_paper_ids AS pids", s=SCOPE_ID)
            counts = {"nodes_by_label": {}, "relationships_by_type": {}}
            for lbl in LABELS:
                counts["nodes_by_label"][lbl] = s.execute_read(
                    q, f"MATCH (n:{lbl}) WHERE n.scope_id = $s RETURN count(n) AS c", s=SCOPE_ID)[0]["c"]
            for t in REL_TYPES:
                counts["relationships_by_type"][t] = s.execute_read(
                    q, f"MATCH ()-[r:{t}]->() WHERE r.scope_id = $s RETURN count(r) AS c", s=SCOPE_ID)[0]["c"]
            counts["server"] = drv.get_server_info().agent
            counts["access_mode"] = "READ (default_access_mode=READ_ACCESS, execute_read)"
    finally:
        drv.close()
    counts["total_nodes"] = sum(counts["nodes_by_label"].values())
    counts["total_relationships"] = sum(counts["relationships_by_type"].values())
    return edges, counts


# --------------------------------------------------------------------------------------------- context
class Context:
    """Local snapshot + raw source metadata used to print evidence for reviewers."""

    def __init__(self) -> None:
        rows = load_dataset(PROCESSED)
        self.rows = rows
        self.papers = {p["id"]: p for p in rows["papers.jsonl"]}
        self.authors = {a["id"]: a for a in rows["authors.jsonl"]}
        self.insts = {i["id"]: i for i in rows["institutions.jsonl"]}
        self.pos = {(r["paper_id"], r["author_id"]): r["position"] for r in rows["paper_authors.jsonl"]}
        self.aff = defaultdict(list)          # (paper, institution) -> [affiliation rows]
        self.aff_pa = {}                      # (paper, author, institution) -> row
        self.inst_papers: dict[str, set[str]] = defaultdict(set)
        for r in rows["affiliations.jsonl"]:
            self.aff[(r["paper_id"], r["institution_id"])].append(r)
            self.aff_pa[(r["paper_id"], r["author_id"], r["institution_id"])] = r
            self.inst_papers[r["institution_id"]].add(r["paper_id"])
        self.topic_span = {(r["paper_id"], r["topic_id"]): r["evidence_span"] for r in rows["paper_topics.jsonl"]}
        self.acl = {r["acl_id"]: r for r in read_jsonl(RAW / "acl_selected.jsonl")}
        self.arx = {r["arxiv_id"]: r for r in read_jsonl(RAW / "arxiv_selected.jsonl")}
        self.oa = {}
        for r in read_jsonl(RAW / "openalex_works.jsonl"):
            if r["openalex"]:
                self.oa[short_oa(r["openalex"]["id"])] = r["openalex"]

    def src(self, pid: str) -> dict[str, Any]:
        p = self.papers[pid]
        return self.acl[p["acl_id"]] if p["source_kind"] == "acl" else self.arx[p["arxiv_id"]]

    def pdf_url(self, pid: str) -> str:
        p = self.papers[pid]
        if p["source_kind"] == "acl":
            return f"https://aclanthology.org/{p['acl_id']}.pdf"
        return f"https://arxiv.org/pdf/{p['arxiv_id']}"

    def printed_name(self, pid: str, position: int) -> str:
        return self.src(pid)["authors"][position - 1]["name"]

    def acl_affiliation(self, pid: str, position: int) -> str | None:
        if self.papers[pid]["source_kind"] != "acl":
            return None
        return self.src(pid)["authors"][position - 1].get("raw_affiliation")

    def openalex_affiliation(self, pid: str, position: int) -> str | None:
        w = self.oa.get(self.papers[pid]["openalex_id"] or "")
        if not w:
            return None
        au = w.get("authorships") or []
        if position - 1 >= len(au):
            return None
        return "; ".join(au[position - 1].get("raw_affiliation_strings") or []) or None

    def author_lines(self, pid: str, aid: str) -> str:
        pos = self.pos[(pid, aid)]
        acl = self.acl_affiliation(pid, pos)
        oa = self.openalex_affiliation(pid, pos)
        acl_txt = f"'{acl}'" if acl else ("(không có trong metadata ACL)" if self.papers[pid]["source_kind"] == "acl"
                                          else "(bài arXiv: metadata không có affiliation – xem PDF)")
        return (f"  - vị trí {pos}: '{self.printed_name(pid, pos)}'\n"
                f"      affiliation in trong ACL Anthology: {acl_txt}\n"
                f"      affiliation theo OpenAlex (chuỗi gốc): {repr(oa) if oa else '(không có)'}")

    def paper_head(self, i: int, pid: str) -> str:
        p = self.papers[pid]
        return f"[P{i}] {p['title']} ({p['year']}) – {p['source_url']} – PDF: {self.pdf_url(pid)}"


# --------------------------------------------------------------------------------------------- strata
def _tier_thresholds(values: list[int]) -> tuple[int, int]:
    v = sorted(values)
    return v[len(v) // 3], v[(2 * len(v)) // 3]


def _tier(x: int, th: tuple[int, int]) -> str:
    return "low" if x <= th[0] else ("mid" if x <= th[1] else "high")


def stratify(ctx: Context, t: str, edges: list[dict[str, Any]]) -> tuple[dict[tuple[str, str], str], dict[str, Any]]:
    freq = {i: len(ps) for i, ps in ctx.inst_papers.items()}

    def key_freq(e):
        if t == "AFFILIATED_WITH":
            return freq.get(e["dst"], 0)
        if t == "ORG_COAUTHORED_WITH":
            return min(freq.get(e["src"], 0), freq.get(e["dst"], 0))
        return freq.get(e["src"], 0)

    def conf(e):
        pids = e["pids"]
        if t == "AFFILIATED_WITH":
            ok = any(ctx.aff_pa.get((p, e["src"], e["dst"]), {}).get("affiliation_check") == "acl_agrees" for p in pids)
            return "acl_backed" if ok else "openalex_only"
        if t == "ORG_COAUTHORED_WITH":
            for p in pids:
                xs = {r["author_id"] for r in ctx.aff[(p, e["src"])] if r.get("affiliation_check") == "acl_agrees"}
                ys = {r["author_id"] for r in ctx.aff[(p, e["dst"])] if r.get("affiliation_check") == "acl_agrees"}
                if any(x != y for x in xs for y in ys):
                    return "acl_backed"
            return "openalex_only"
        n = sum(1 for p in pids if any(r.get("affiliation_check") == "acl_agrees" for r in ctx.aff[(p, e["src"])]))
        return "acl_backed" if n >= 2 else "openalex_only"

    th = _tier_thresholds([key_freq(e) for e in edges])
    strata = {(e["src"], e["dst"]): f"{_tier(key_freq(e), th)}|{conf(e)}" for e in edges}
    info = {"frequency_key": {"AFFILIATED_WITH": "papers of target institution",
                              "ORG_COAUTHORED_WITH": "min(papers of the two institutions)",
                              "ACTIVE_IN": "papers of source institution"}[t],
            "tier_thresholds(low<=a, mid<=b, high>b)": list(th),
            "confidence_definition": {"AFFILIATED_WITH": "acl_backed if any evidence authorship has an ACL-printed affiliation agreeing",
                                      "ORG_COAUTHORED_WITH": "acl_backed if on some paper two different authors have ACL-agreeing rows",
                                      "ACTIVE_IN": "acl_backed if >=2 evidence papers carry the institution via an ACL-agreeing row"}[t],
            "population_by_stratum": dict(sorted(Counter(strata.values()).items()))}
    return strata, info


def allocate(sizes: dict[str, int], n: int) -> dict[str, int]:
    """Proportional allocation (largest remainder), capped by stratum size."""
    total = sum(sizes.values())
    if total <= n:
        return dict(sizes)
    raw = {k: n * v / total for k, v in sizes.items()}
    alloc = {k: min(int(raw[k]), sizes[k]) for k in sizes}
    rest = n - sum(alloc.values())
    for k in sorted(sizes, key=lambda k: (-(raw[k] - int(raw[k])), k)):
        if rest == 0:
            break
        if alloc[k] < sizes[k]:
            alloc[k] += 1
            rest -= 1
    return alloc


def two_round_sample(edges: list[dict[str, Any]], strata: dict[tuple[str, str], str], seed: int,
                     per_round: int = PER_ROUND) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rng = random.Random(seed)
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in sorted(edges, key=lambda e: (e["src"], e["dst"])):
        by[strata[(e["src"], e["dst"])]].append(e)
    for k in sorted(by):
        rng.shuffle(by[k])
    a1 = allocate({k: len(v) for k, v in by.items()}, per_round)
    r1 = [e for k in sorted(by) for e in by[k][: a1[k]]]
    rem = {k: len(v) - a1[k] for k, v in by.items()}
    a2 = allocate(rem, per_round)
    r2 = [e for k in sorted(by) for e in by[k][a1[k]: a1[k] + a2[k]]]
    for e in r1 + r2:
        e["stratum"] = strata[(e["src"], e["dst"])]
    return r1, r2


# --------------------------------------------------------------------------------------------- sheet rows
def supporting(ctx: Context, pids: list[str]) -> str:
    return "\n".join(f"P{i}: {ctx.papers[p]['title']} ({ctx.papers[p]['year']}) | {ctx.papers[p]['source_url']}"
                     for i, p in enumerate(pids, 1))


def evidence(ctx: Context, t: str, e: dict[str, Any]) -> str:
    out = []
    if t == "AFFILIATED_WITH":
        for i, p in enumerate(e["pids"], 1):
            out.append(ctx.paper_head(i, p))
            out.append(f"  tác giả cần kiểm (theo vị trí):\n{ctx.author_lines(p, e['src'])}")
    elif t == "ORG_COAUTHORED_WITH":
        a, b = ctx.insts[e["src"]]["name"], ctx.insts[e["dst"]]["name"]
        for i, p in enumerate(e["pids"], 1):
            out.append(ctx.paper_head(i, p))
            for label, iid in ((a, e["src"]), (b, e["dst"])):
                out.append(f"  tác giả được gán '{label}':")
                for r in sorted(ctx.aff[(p, iid)], key=lambda r: ctx.pos[(p, r['author_id'])]):
                    out.append(ctx.author_lines(p, r["author_id"]))
    else:  # ACTIVE_IN
        topic = e["dst"].split(":", 1)[1]
        out.append(f"Chủ đề: {topic} ({TOPIC_VI[topic]}). Cần >= 2 bài thỏa: có tác giả khai báo tổ chức VÀ bài thuộc chủ đề.")
        for i, p in enumerate(e["pids"], 1):
            out.append(ctx.paper_head(i, p))
            out.append(f"  cụm từ trong title/abstract liên quan chủ đề: '{ctx.topic_span.get((p, topic), '')}'")
            out.append("  tác giả được gán tổ chức này:")
            for r in sorted(ctx.aff[(p, e["src"])], key=lambda r: ctx.pos[(p, r['author_id'])]):
                out.append(ctx.author_lines(p, r["author_id"]))
    return "\n".join(out)


def entity_name(ctx: Context, i: str) -> str:
    if i in ctx.authors:
        return ctx.authors[i]["name"]
    if i in ctx.insts:
        return ctx.insts[i]["name"]
    if i.startswith("topic:"):
        k = i.split(":", 1)[1]
        return f"{k} ({TOPIC_VI[k]})"
    return i


def build_rows(ctx: Context, sample: dict[str, list[dict[str, Any]]], round_no: int) -> list[dict[str, Any]]:
    # anchor each row on the evidence paper most shared within this round, so one opened PDF covers many rows
    pf = Counter(p for es in sample.values() for e in es for p in e["pids"])
    rows = []
    for t, es in sample.items():
        for e in es:
            anchor = max(e["pids"], key=lambda p: (pf[p], p))
            pids = [anchor] + [p for p in e["pids"] if p != anchor]
            e["pids"] = pids
            p = ctx.papers[anchor]
            rows.append({
                "review_id": "", "round": round_no, "is_overlap": 0, "edge_type": t,
                "source_id": e["src"], "source_name": entity_name(ctx, e["src"]),
                "target_id": e["dst"], "target_name": entity_name(ctx, e["dst"]),
                "paper_id": anchor, "paper_title": p["title"], "paper_url": p["source_url"], "pdf_url": ctx.pdf_url(anchor),
                "year": p["year"], "n_supporting_papers": len(pids), "supporting_papers": supporting(ctx, pids),
                "evidence_text": evidence(ctx, t, e), **{c: "" for c in LABEL_COLUMNS},
            })
    rows.sort(key=lambda r: (r["paper_id"], TYPES.index(r["edge_type"]), r["source_id"], r["target_id"]))
    prefix = {"AFFILIATED_WITH": "AFF", "ORG_COAUTHORED_WITH": "ORG", "ACTIVE_IN": "ACT"}
    for i, r in enumerate(rows, 1):
        r["review_id"] = f"R{round_no}-{i:03d}-{prefix[r['edge_type']]}"
    return rows


def write_sheet(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:   # BOM so Excel detects UTF-8
        w = csv.DictWriter(fh, fieldnames=SHEET_COLUMNS, quoting=csv.QUOTE_ALL)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in SHEET_COLUMNS})


def write_plain(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows([{k: r.get(k, "") for k in fields} for r in rows])


def git_state() -> dict[str, str]:
    def g(*a):
        return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return {"head": g("rev-parse", "HEAD"), "head_short": g("rev-parse", "--short", "HEAD"),
            "dirty_files": g("status", "--porcelain")}


# --------------------------------------------------------------------------------------------- main
def main(seed: int = SEED) -> int:
    load_env()
    setup_logging()
    out1 = EVAL / "review_sheet_round1.csv"
    if out1.exists() and any(r.get("label") for r in csv.DictReader(open(out1, encoding="utf-8-sig"))):
        log.error("%s already contains labels; refusing to overwrite", out1)
        return 2
    git = git_state()
    aura_edges, aura_counts = read_edges_from_aura()
    ctx = Context()
    local = derive_edges(ctx.rows)

    # --- integrity: AuraDB must hold exactly the local snapshot's edges for the 3 types
    mism = {}
    for t in TYPES:
        a = {(e["src"], e["dst"], tuple(sorted(e["pids"]))) for e in aura_edges[t]}
        l = {(e["from"], e["to"], tuple(e["evidence_paper_ids"])) for e in local[t]}
        if a != l:
            mism[t] = {"aura_only": len(a - l), "local_only": len(l - a)}
    if mism:
        log.error("AuraDB and local snapshot differ: %s - aborting", mism)
        return 3
    manifest = read_json(PROCESSED / "manifest.json")

    rng_master = random.Random(seed)
    round1, round2, strata_info = {}, {}, {}
    for t in TYPES:
        edges = [{"src": e["src"], "dst": e["dst"], "pids": sorted(e["pids"])} for e in aura_edges[t]]
        strata, info = stratify(ctx, t, edges)
        r1, r2 = two_round_sample(edges, strata, seed=rng_master.randrange(2**31))
        assert not {(e["src"], e["dst"]) for e in r1} & {(e["src"], e["dst"]) for e in r2}
        info["round1_by_stratum"] = dict(sorted(Counter(e["stratum"] for e in r1).items()))
        info["round2_by_stratum"] = dict(sorted(Counter(e["stratum"] for e in r2).items()))
        info["population"] = len(edges)
        round1[t], round2[t], strata_info[t] = r1, r2, info

    rows1 = build_rows(ctx, {t: [dict(e) for e in v] for t, v in round1.items()}, 1)
    ov_rng = random.Random(seed + 1)
    overlap_ids = set()
    for t in TYPES:
        ids = sorted(r["review_id"] for r in rows1 if r["edge_type"] == t)
        overlap_ids |= set(ov_rng.sample(ids, min(OVERLAP_PER_TYPE, len(ids))))
    for r in rows1:
        r["is_overlap"] = int(r["review_id"] in overlap_ids)
    rows2 = build_rows(ctx, {t: [dict(e) for e in v] for t, v in round2.items()}, 2)

    write_sheet(out1, rows1)
    write_sheet(EVAL / "review_sheet_round1_overlap_reviewer2.csv", [r for r in rows1 if r["is_overlap"]])
    # hidden from reviewers: strata + reserved round 2 (prebuilt in the same structure)
    write_plain(SAMPLING / "round1_strata.csv",
                [{"review_id": r["review_id"], "edge_type": r["edge_type"], "source_id": r["source_id"],
                  "target_id": r["target_id"], "stratum": s}
                 for r, s in _strata_for(rows1, round1)], ["review_id", "edge_type", "source_id", "target_id", "stratum"])
    write_sheet(SAMPLING / "round2_prebuilt_DO_NOT_REVIEW.csv", rows2)
    write_plain(SAMPLING / "round2_reserved.csv",
                [{"review_id": r["review_id"], "edge_type": r["edge_type"], "source_id": r["source_id"],
                  "target_id": r["target_id"], "stratum": s}
                 for r, s in _strata_for(rows2, round2)], ["review_id", "edge_type", "source_id", "target_id", "stratum"])
    meta = {
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "seed": seed,
        "overlap_seed": seed + 1, "per_round_per_type": PER_ROUND, "overlap_per_type": OVERLAP_PER_TYPE,
        "git": {k: v for k, v in git.items() if k != "dirty_files"}, "git_dirty_files": git["dirty_files"].splitlines(),
        "aura_counts": aura_counts, "aura_matches_local_snapshot": True,
        "manifest_created_at_utc": manifest["created_at_utc"], "manifest_checksums": manifest["checksums"],
        "manifest_sha256": hashlib.sha256((PROCESSED / "manifest.json").read_bytes()).hexdigest(),
        "strata": strata_info,
        "round1_rows": len(rows1), "round1_distinct_anchor_papers": len({r["paper_id"] for r in rows1}),
        "round2_reserved_rows": len(rows2),
        "round1_supporting_papers_total": sum(r["n_supporting_papers"] for r in rows1),
    }
    write_json(SAMPLING / "sampling_meta.json", meta)
    log.info("round1: %d rows (%d anchor papers), overlap %d; round2 reserved %d", len(rows1),
             meta["round1_distinct_anchor_papers"], len(overlap_ids), len(rows2))
    print(meta["strata"])
    return 0


def _strata_for(rows: list[dict[str, Any]], sample: dict[str, list[dict[str, Any]]]):
    s = {(t, e["src"], e["dst"]): e["stratum"] for t, es in sample.items() for e in es}
    return [(r, s[(r["edge_type"], r["source_id"], r["target_id"])]) for r in rows]


if __name__ == "__main__":
    raise SystemExit(main())
