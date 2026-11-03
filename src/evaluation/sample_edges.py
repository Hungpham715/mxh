"""Stratified edge sampling + automated structural checks + source-evidence verification.

Two levels, kept strictly apart:
  * structural_checks.json  - every edge, machine checks of type/endpoints/thresholds/direction/dedup.
  * automated_labels.csv    - sampled edges re-verified against the raw source records (ACL XML, arXiv feed,
                              OpenAlex work JSON) cached on disk; label_origin = automated_preliminary.
                              This is NOT independent human annotation.
  * manual_review_template.csv - blank sheet for human reviewers.
"""
from __future__ import annotations

import csv
import random
from collections import Counter, defaultdict
from typing import Any

from src.common import EVAL, PROCESSED, RAW, log, read_jsonl, write_json
from src.data.affil import affiliation_agrees
from src.data.contracts import load_dataset
from src.data.normalize import fold, name_compatible, short_oa
from src.data.topics import TopicClassifier
from src.common import ROOT
from src.graph.derive import MIN_TOPIC_PAPERS, REL_SCHEMA, REL_TYPES, derive_edges


class SourceIndex:
    """Raw source records to re-check edges against (independent of the processed JSONL)."""

    def __init__(self) -> None:
        self.acl = {r["acl_id"]: r for r in read_jsonl(RAW / "acl_selected.jsonl")}
        arx = RAW / "arxiv_selected.jsonl"
        self.arxiv = {r["arxiv_id"]: r for r in read_jsonl(arx)} if arx.exists() else {}
        self.oa: dict[str, dict[str, Any]] = {}
        for r in read_jsonl(RAW / "openalex_works.jsonl"):
            if r["openalex"]:
                self.oa[short_oa(r["openalex"]["id"]) or ""] = r["openalex"]

    def source_record(self, paper: dict[str, Any]) -> dict[str, Any] | None:
        if paper["source_kind"] == "acl":
            return self.acl.get(paper["acl_id"])
        return self.arxiv.get(paper["arxiv_id"])


def _author_at(src: dict[str, Any] | None, author: dict[str, Any], paper_oa: dict[str, Any] | None) -> int | None:
    """Return the 1-based position of `author` in the raw source author list, or None."""
    if src is None:
        return None
    if author["openalex_id"] and paper_oa:
        for i, a in enumerate(paper_oa.get("authorships") or [], 1):
            if short_oa((a.get("author") or {}).get("id")) == author["openalex_id"]:
                if i <= len(src["authors"]) and name_compatible(src["authors"][i - 1]["name"], author["name"]):
                    return i
        return None
    for a in src["authors"]:
        if fold(a["name"]) == fold(author["name"]):
            return a["position"]
    return None


class Verifier:
    def __init__(self, rows: dict[str, list[dict[str, Any]]]):
        self.papers = {p["id"]: p for p in rows["papers.jsonl"]}
        self.authors = {a["id"]: a for a in rows["authors.jsonl"]}
        self.insts = {i["id"]: i for i in rows["institutions.jsonl"]}
        self.venues = {v["id"]: v for v in rows["venues.jsonl"]}
        self.aff_authors: dict[tuple[str, str], set[str]] = defaultdict(set)
        for r in rows["affiliations.jsonl"]:
            self.aff_authors[(r["paper_id"], r["institution_id"])].add(r["author_id"])
        self.src = SourceIndex()
        self.clf = TopicClassifier.from_file(ROOT / "configs" / "topics.yaml")

    def _oa(self, pid: str) -> dict[str, Any] | None:
        p = self.papers[pid]
        return self.src.oa.get(p["openalex_id"]) if p["openalex_id"] else None

    def _pos(self, aid: str, pid: str) -> int | None:
        p = self.papers[pid]
        return _author_at(self.src.source_record(p), self.authors[aid], self._oa(pid))

    def _inst_on(self, aid: str, iid: str, pid: str) -> bool:
        w = self._oa(pid)
        a = self.authors[aid]
        if not w or not a["openalex_id"]:
            return False
        for au in w.get("authorships") or []:
            if short_oa((au.get("author") or {}).get("id")) == a["openalex_id"]:
                return any(short_oa(i.get("id")) == iid.split(":", 1)[1] for i in au.get("institutions") or [])
        return False

    def _declared(self, aid: str, pid: str) -> str | None:
        """Affiliation string printed in the ACL Anthology XML for this authorship (independent of OpenAlex)."""
        p = self.papers[pid]
        if p["source_kind"] != "acl":
            return None
        pos = self._pos(aid, pid)
        src = self.src.source_record(p)
        if pos is None or src is None:
            return None
        return src["authors"][pos - 1].get("raw_affiliation")

    def _aff_independent(self, aid: str, iid: str, pid: str) -> str:
        """'agree' | 'disagree' | 'none' : institution vs ACL-declared affiliation on that paper."""
        d = self._declared(aid, pid)
        if not d:
            return "none"
        return "agree" if affiliation_agrees(self.insts[iid]["name"], d) else "disagree"

    def _topic_on(self, pid: str, topic: str) -> bool:
        p = self.papers[pid]
        src = self.src.source_record(p)
        title = src["title"] if src else None
        abstract = (src or {}).get("abstract") or p.get("abstract")
        return any(t["topic_id"] == topic for t in self.clf.classify(title, abstract).topics)

    def verify(self, e: dict[str, Any]) -> tuple[str, str, list[str]]:
        """Return (label, reason, evidence_urls). label in correct|incorrect|unverifiable."""
        t, f, to = e["type"], e["from"], e["to"]
        pids = e["evidence_paper_ids"]
        urls = [self.papers[p]["source_url"] for p in pids[:3]]
        try:
            if t in ("FIRST_AUTHOR_OF", "OTHER_AUTHOR_OF"):
                pos = self._pos(f, to)
                if pos is None:
                    return "unverifiable", "author not locatable in raw source author list", urls
                ok = (pos == 1) == (t == "FIRST_AUTHOR_OF")
                return ("correct", f"source position {pos}", urls) if ok else ("incorrect", f"derivation: source position {pos}", urls)
            if t == "COAUTHORED_WITH":
                for p in pids:
                    if self._pos(f, p) is None or self._pos(to, p) is None:
                        return "incorrect" if self.authors[f]["openalex_id"] else "unverifiable", f"identity: pair not both on {p}", urls
                return "correct", f"both authors listed on {len(pids)} paper(s)", urls
            if t == "AFFILIATED_WITH":
                bad = [p for p in pids if not self._inst_on(f, to, p)]
                if bad:
                    return "incorrect", f"affiliation: institution not in OpenAlex authorship of {bad[0]}", urls
                ind = [self._aff_independent(f, to, p) for p in pids]
                if "agree" in ind:
                    return "correct", "institution matches ACL-declared affiliation on an evidence paper", [self.insts[to]["source_url"]] + urls
                if "disagree" in ind:
                    return "incorrect", "affiliation: OpenAlex institution disagrees with ACL-declared affiliation", urls
                return "unverifiable", "missing source: no independent (ACL-printed) affiliation; OpenAlex only", urls
            if t == "APPEARS_IN":
                p = self.papers[f]
                v = self.venues[to]
                if p["source_kind"] == "acl":
                    coll_vol = to.split("venue:acl:", 1)[-1]
                    ok = p["acl_id"].startswith(coll_vol + ".")
                else:
                    src = self.src.source_record(p)
                    ok = bool(src) and src["primary_category"] == "cs.CL" and v["kind"] == "preprint_server"
                return ("correct", "venue matches source id/category", urls) if ok else ("incorrect", "derivation: venue mismatch", urls)
            if t == "HAS_TOPIC":
                topic = to.split(":", 1)[1]
                return ("correct", "rule re-applied on raw source title/abstract", urls) if self._topic_on(f, topic) \
                    else ("incorrect", "topic: rule does not fire on raw source text", urls)
            if t == "CITES":
                w = self._oa(f)
                tgt = self.papers[to]["openalex_id"]
                if not w:
                    return "unverifiable", "missing source: citing work not in OpenAlex cache", urls
                refs = {short_oa(r) for r in w.get("referenced_works") or []}
                return ("correct", "target in referenced_works of citing work", urls) if tgt in refs \
                    else ("incorrect", "citation: target not in referenced_works", urls)
            if t == "ORG_COAUTHORED_WITH":
                # per evidence paper: authors carrying f and `to` (from the snapshot); each authorship is checked
                # against the affiliation that same author printed in the ACL XML (independent of OpenAlex)
                any_unknown = False
                for p in pids:
                    xs = self.aff_authors.get((p, f), set())
                    ys = self.aff_authors.get((p, to), set())
                    vx = {x: self._aff_independent(x, f, p) for x in xs}
                    vy = {y: self._aff_independent(y, to, p) for y in ys}
                    if any(vx[x] == "agree" and vy[y] == "agree" and x != y for x in xs for y in ys):
                        return "correct", f"ACL XML: two different authors print the two institutions on {p}", urls
                    if any(v == "none" for v in list(vx.values()) + list(vy.values())):
                        any_unknown = True
                if any_unknown:
                    return "unverifiable", "missing source: at least one authorship has no ACL-printed affiliation", urls
                return "incorrect", "affiliation: ACL-printed affiliations contradict the pair", urls
            if t == "RESEARCHES":
                topic = to.split(":", 1)[1]
                good = [p for p in pids if self._pos(f, p) is not None and self._topic_on(p, topic)]
                if len(set(good)) >= MIN_TOPIC_PAPERS:
                    return "correct", f"{len(good)} source-verified papers with topic", urls
                return "incorrect", f"derivation: only {len(good)} source-verified papers", urls
            if t == "ACTIVE_IN":
                topic = to.split(":", 1)[1]
                good, unknown = [], 0
                for p in pids:
                    if not self._topic_on(p, topic):
                        continue
                    verdicts = [self._aff_independent(a, f, p) for a in self.aff_authors.get((p, f), set())]
                    if "agree" in verdicts:
                        good.append(p)
                    elif "none" in verdicts:
                        unknown += 1
                if len(set(good)) >= MIN_TOPIC_PAPERS:
                    return "correct", f"{len(good)} papers with topic where an ACL-printed affiliation matches", urls
                if len(set(good)) + unknown >= MIN_TOPIC_PAPERS:
                    return "unverifiable", f"only {len(good)} independently verified, {unknown} without ACL affiliation", urls
                return "incorrect", f"affiliation: only {len(good)} papers independently support the institution", urls
        except KeyError as exc:
            return "unverifiable", f"missing source: {exc}", urls
        return "unverifiable", "no verifier", urls


def structural_checks(rows: dict[str, list[dict[str, Any]]], edges: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    papers = {p["id"] for p in rows["papers.jsonl"]}
    ids = {"Author": {a["id"] for a in rows["authors.jsonl"]}, "Paper": papers,
           "Institution": {i["id"] for i in rows["institutions.jsonl"]}, "Venue": {v["id"] for v in rows["venues.jsonl"]},
           "Topic": {f"topic:{t}" for t in ("llm", "mt", "qa", "retrieval", "summarization", "safety_eval")}}
    out: dict[str, Any] = {}
    invalid: list[dict[str, Any]] = []
    for t in REL_TYPES:
        fl, tl, undirected = REL_SCHEMA[t]
        c: Counter[str] = Counter()
        seen = set()
        for e in edges[t]:
            c["checked"] += 1
            probs = []
            if e["from"] not in ids[fl] or e["to"] not in ids[tl]:
                probs.append("endpoint")
            if not e["evidence_paper_ids"] or any(p not in papers for p in e["evidence_paper_ids"]):
                probs.append("evidence")
            key = (e["from"], e["to"])
            if key in seen or (undirected and (e["to"], e["from"]) in seen):
                probs.append("duplicate")
            seen.add(key)
            if undirected and not e["from"] < e["to"]:
                probs.append("non_canonical_pair")
            if e["from"] == e["to"]:
                probs.append("self_loop")
            if t in ("RESEARCHES", "ACTIVE_IN") and e["evidence_count"] < MIN_TOPIC_PAPERS:
                probs.append("threshold")
            if t == "CITES" and e["evidence_paper_ids"] != [e["from"]]:
                probs.append("direction")
            for p in probs:
                c[p] += 1
            if probs:
                c["invalid"] += 1
                if len(invalid) < 200:
                    invalid.append({"type": t, "from": e["from"], "to": e["to"], "problems": probs})
        out[t] = dict(c)
    write_json(EVAL / "invalid_edges_sample.json", invalid)
    return out


FIELDS = ["sample_id", "type", "from_id", "from_name", "to_id", "to_name", "evidence_paper_ids",
          "evidence_titles", "evidence_urls", "graph_count_type"]


def _name(rows_idx: dict[str, dict[str, Any]], i: str) -> str:
    r = rows_idx.get(i)
    return (r.get("name") or r.get("title") or i) if r else i


def run_sample(per_type: int = 20, seed: int = 20261107, tag: str | None = None) -> int:
    rows = load_dataset(PROCESSED)
    edges = derive_edges(rows)
    EVAL.mkdir(parents=True, exist_ok=True)
    sc = structural_checks(rows, edges)
    write_json(EVAL / "structural_checks.json", sc)
    idx: dict[str, dict[str, Any]] = {}
    for f in ("papers.jsonl", "authors.jsonl", "institutions.jsonl", "venues.jsonl"):
        idx.update({r["id"]: r for r in rows[f]})
    papers = {p["id"]: p for p in rows["papers.jsonl"]}
    rng = random.Random(seed)
    verifier = Verifier(rows)
    sample_rows, auto_rows = [], []
    for t in REL_TYPES:
        pool = sorted(edges[t], key=lambda e: (e["from"], e["to"]))
        pick = pool if len(pool) <= per_type else rng.sample(pool, per_type)
        for k, e in enumerate(pick, 1):
            sid = f"{t}-{k:02d}"
            pids = e["evidence_paper_ids"]
            sample_rows.append({
                "sample_id": sid, "type": t, "from_id": e["from"], "from_name": _name(idx, e["from"]),
                "to_id": e["to"], "to_name": _name(idx, e["to"]), "evidence_paper_ids": "|".join(pids[:5]),
                "evidence_titles": " || ".join(papers[p]["title"] for p in pids[:3]),
                "evidence_urls": " ".join(papers[p]["source_url"] for p in pids[:3]),
                "graph_count_type": len(pool)})
            label, reason, urls = verifier.verify(e)
            auto_rows.append({"sample_id": sid, "type": t, "label": label, "error_reason": "" if label == "correct" else reason,
                              "note": reason, "evidence_urls": " ".join(urls), "graph_count_type": len(pool),
                              "label_origin": "automated_preliminary"})
    suffix = f"_{tag}" if tag else ""
    with open(EVAL / f"samples{suffix}.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(sample_rows)
    with open(EVAL / f"automated_labels{suffix}.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(auto_rows[0]))
        w.writeheader()
        w.writerows(auto_rows)
    with open(EVAL / "manual_review_template.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(FIELDS + ["reviewer", "label(correct|incorrect|unverifiable)", "error_reason", "note"])
        for r in sample_rows:
            w.writerow([r[k] for k in FIELDS] + ["", "", "", ""])
    write_json(EVAL / "sample_meta.json", {"seed": seed, "per_type": per_type,
                                          "n_samples": len(sample_rows),
                                          "per_type_counts": dict(Counter(r["type"] for r in sample_rows))})
    log.info("sampled %d edges; automated labels: %s", len(sample_rows), dict(Counter(r["label"] for r in auto_rows)))
    return 0
