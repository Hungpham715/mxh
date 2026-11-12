"""Normalise raw ACL/arXiv/OpenAlex records into canonical entities (no fuzzy merging)."""
from __future__ import annotations

import csv
import re
import unicodedata
from collections import Counter
from typing import Any

from src.common import REJECTED, log

OA = "https://openalex.org/"


def short_oa(url: str | None) -> str | None:
    if not url:
        return None
    return url.rsplit("/", 1)[-1]


def fold(s: str | None) -> str:
    s = (s or "").replace("ı", "i").replace("ł", "l").replace("ø", "o").replace("đ", "d").replace("Đ", "D")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower()).strip()


def name_compatible(src_name: str, oa_name: str) -> bool:
    """Weak sanity check that position i in the source and in OpenAlex is the same person.
    Requires the source family name (last token) to appear among the OpenAlex name tokens or vice versa."""
    a, b = fold(src_name).split(), fold(oa_name).split()
    if not a or not b:
        return False
    return a[-1] in b or b[-1] in a or a[0] == b[-1] or b[0] == a[-1]


def title_tokens(t: str | None) -> set[str]:
    return {w for w in fold(t).split() if len(w) > 2}


def same_title(a: str | None, b: str | None) -> bool:
    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= 0.6


def invert_abstract(inv: dict[str, list[int]] | None) -> str | None:
    if not inv:
        return None
    pos: dict[int, str] = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos)) or None


def author_position_label(pos: int, n: int) -> str:
    if pos == 1:
        return "first"
    return "last" if pos == n else "middle"


class Normalizer:
    def __init__(self, acl: list[dict[str, Any]], arxiv: list[dict[str, Any]], oa_rows: list[dict[str, Any]]):
        self.acl, self.arxiv = acl, arxiv
        self.oa = {(r["source_kind"], r["source_id"]): r["openalex"] for r in oa_rows}
        self.unresolved: list[dict[str, Any]] = []
        self.stats: Counter[str] = Counter()

    def _unres(self, kind: str, ref: str, detail: str) -> None:
        self.unresolved.append({"kind": kind, "ref": ref, "detail": detail})

    def run(self) -> dict[str, list[dict[str, Any]]]:
        papers: dict[str, dict[str, Any]] = {}
        work_owner: dict[str, str] = {}      # OpenAlex W -> paper id
        doi_owner: dict[str, str] = {}
        venues: dict[str, dict[str, Any]] = {}
        sources: dict[str, tuple[dict[str, Any], dict[str, Any] | None]] = {}

        # ACL first so that ACL wins when a work also exists as an arXiv preprint
        for rec in sorted(self.acl, key=lambda r: (r["collection"], r["volume"], r["paper_num"])):
            work = self.oa.get(("acl", rec["acl_id"]))
            wid = short_oa(work["id"]) if work else None
            if wid and wid in work_owner:
                self._unres("paper_duplicate_work", rec["acl_id"], f"OpenAlex {wid} already used by {work_owner[wid]}")
                wid, work = None, None
            pid = f"oa:{wid}" if wid else f"acl:{rec['acl_id']}"
            vid = f"venue:acl:{rec['collection']}-{rec['volume']}"
            venues.setdefault(vid, {"id": vid, "name": rec["volume_title"] or vid, "kind": "conference",
                                    "year": rec["year"],
                                    "source_url": f"https://aclanthology.org/volumes/{rec['collection']}-{rec['volume']}/"})
            abstract, origin = rec["abstract"], "acl"
            if not abstract and work and work.get("abstract_inverted_index"):
                abstract, origin = invert_abstract(work["abstract_inverted_index"]), "openalex_inverted_index"
            papers[pid] = {
                "id": pid, "title": rec["title"], "year": rec["year"], "abstract": abstract,
                "doi": rec["doi"], "acl_id": rec["acl_id"], "arxiv_id": None, "source_kind": "acl",
                "source_url": rec["url"], "venue_id": vid, "openalex_id": wid,
                "abstract_origin": origin if abstract else None, "alias_source_urls": [],
            }
            if wid:
                work_owner[wid] = pid
            if rec["doi"]:
                doi_owner[rec["doi"]] = pid
            sources[pid] = (rec, work)

        arx_vid = "venue:arxiv:cs.CL"
        for rec in sorted(self.arxiv, key=lambda r: r["arxiv_id"]):
            work = self.oa.get(("arxiv", rec["arxiv_id"]))
            wid = short_oa(work["id"]) if work else None
            owner = work_owner.get(wid) if wid else None
            if owner is None and rec.get("journal_doi") and rec["journal_doi"] in doi_owner:
                owner = doi_owner[rec["journal_doi"]]
            if owner is not None:
                if same_title(papers[owner]["title"], rec["title"]) and papers[owner]["arxiv_id"] is None:
                    papers[owner]["arxiv_id"] = rec["arxiv_id"]
                    papers[owner]["alias_source_urls"].append(rec["url"])
                    self.stats["arxiv_merged_into_acl"] += 1
                    continue
                self._unres("paper_merge_conflict", rec["arxiv_id"],
                            f"same OpenAlex work/DOI as {owner} but title differs or alias taken; kept separate without OpenAlex id")
                wid, work = None, None
            venues.setdefault(arx_vid, {"id": arx_vid, "name": "arXiv cs.CL (preprint)", "kind": "preprint_server",
                                        "year": None, "source_url": "https://arxiv.org/list/cs.CL/"})
            pid = f"oa:{wid}" if wid else f"arxiv:{rec['arxiv_id']}"
            abstract, origin = rec["abstract"], "arxiv"
            if not abstract and work and work.get("abstract_inverted_index"):
                abstract, origin = invert_abstract(work["abstract_inverted_index"]), "openalex_inverted_index"
            papers[pid] = {
                "id": pid, "title": rec["title"], "year": rec["year"], "abstract": abstract,
                "doi": f"10.48550/arxiv.{rec['arxiv_id']}".lower(), "acl_id": None, "arxiv_id": rec["arxiv_id"],
                "source_kind": "arxiv", "source_url": rec["url"], "venue_id": arx_vid, "openalex_id": wid,
                "abstract_origin": origin if abstract else None, "alias_source_urls": [],
            }
            if wid:
                work_owner[wid] = pid
            sources[pid] = (rec, work)

        # ---------------- authors / affiliations
        from src.data.affil import affiliation_agrees, is_smeared  # local import avoids a cycle (affil uses fold)
        authors: dict[str, dict[str, Any]] = {}
        insts: dict[str, dict[str, Any]] = {}
        paper_authors, affiliations = [], []
        for pid in sorted(papers):
            rec, work = sources[pid]
            p = papers[pid]
            src_auth = rec["authors"]
            n = len(src_auth)
            oa_auth = (work or {}).get("authorships") or []
            aligned = bool(work) and len(oa_auth) == n
            if work and not aligned:
                self._unres("authorship_count_mismatch", pid, f"source {n} authors vs OpenAlex {len(oa_auth)}")
                self.stats["authorship_count_mismatch"] += 1
            used: set[str] = set()
            for a in src_auth:
                pos = a["position"]
                oa_a = oa_auth[pos - 1] if aligned else None
                aid, status, oa_aid = None, "source_only", None
                if oa_a and oa_a.get("author", {}).get("id"):
                    cand = short_oa(oa_a["author"]["id"])
                    if not name_compatible(a["name"], oa_a["author"].get("display_name", "")):
                        self._unres("author_name_mismatch", f"{pid}#{pos}",
                                    f"source '{a['name']}' vs OpenAlex '{oa_a['author'].get('display_name')}' ({cand})")
                        status = "unresolved"
                    elif cand in used:
                        self._unres("author_duplicate_in_paper", f"{pid}#{pos}", f"{cand} appears twice")
                        status = "unresolved"
                    else:
                        aid, status, oa_aid = f"oa:{cand}", "verified", cand
                        used.add(cand)
                if aid is None:
                    # scoped to this authorship only -> can never link across papers
                    aid = f"src:{pid}#{pos}"
                orcid = a.get("orcid")
                if not orcid and oa_a and status == "verified":
                    orcid = short_oa(oa_a["author"].get("orcid"))
                if aid not in authors:
                    authors[aid] = {"id": aid, "name": a["name"], "orcid": orcid, "openalex_id": oa_aid,
                                    "acl_author_id": a.get("acl_author_id"), "identity_status": status}
                else:
                    authors[aid]["orcid"] = authors[aid]["orcid"] or orcid
                    authors[aid]["acl_author_id"] = authors[aid]["acl_author_id"] or a.get("acl_author_id")
                self.stats[f"authorship_{status}"] += 1
                paper_authors.append({"paper_id": pid, "author_id": aid, "position": pos,
                                      "author_position": author_position_label(pos, n),
                                      "source_url": p["source_url"]})
                if status != "verified" or oa_a is None:
                    continue
                raw = "; ".join(oa_a.get("raw_affiliation_strings") or []) or a.get("raw_affiliation")
                seen_i: set[str] = set()
                smeared = bool(work) and is_smeared(work)
                declared = a.get("raw_affiliation")   # printed in the ACL Anthology XML for this authorship
                for inst in oa_a.get("institutions") or []:
                    iid = short_oa(inst.get("id"))
                    if not iid or iid in seen_i or not inst.get("display_name"):
                        continue
                    check = "openalex_only"
                    if declared:
                        # ACL Anthology prints the author's own affiliation: an OpenAlex institution that contradicts
                        # it is dropped (QA round 1 found OpenAlex mis-assignments, see evaluation/fix_log.json)
                        if not affiliation_agrees(inst["display_name"], declared):
                            self.stats["affiliation_dropped_conflicts_acl"] += 1
                            self._unres("affiliation_conflict_acl", f"{pid}#{pos}",
                                        f"OpenAlex '{inst['display_name']}' vs ACL '{declared}'")
                            continue
                        check = "acl_agrees"
                    elif smeared:
                        # paper-level affiliations copied onto every author and nothing to disambiguate -> drop
                        self.stats["smeared_affiliation_dropped"] += 1
                        continue
                    seen_i.add(iid)
                    insts.setdefault(f"oa:{iid}", {"id": f"oa:{iid}", "name": inst["display_name"],
                                                   "ror": inst.get("ror"), "country_code": inst.get("country_code"),
                                                   "source_url": f"{OA}{iid}"})
                    affiliations.append({"paper_id": pid, "author_id": aid, "institution_id": f"oa:{iid}",
                                         "year": p["year"], "raw_affiliation": declared or raw,
                                         "source_url": f"{OA}{p['openalex_id']}", "affiliation_check": check})
                if not seen_i:
                    self.stats["verified_authorship_without_institution"] += 1

        # ---------------- citations (both ends in corpus)
        citations = []
        for pid in sorted(papers):
            _, work = sources[pid]
            if not work:
                continue
            targets = set()
            for ref in work.get("referenced_works") or []:
                tgt = work_owner.get(short_oa(ref) or "")
                if tgt and tgt != pid:
                    targets.add(tgt)
            for tgt in sorted(targets):
                citations.append({"citing_paper_id": pid, "cited_paper_id": tgt,
                                  "source_url": f"{OA}{papers[pid]['openalex_id']}"})
            self.stats["papers_with_references"] += bool(work.get("referenced_works"))

        self.stats["papers"] = len(papers)
        self.stats["unmatched_openalex"] = sum(1 for p in papers.values() if not p["openalex_id"])
        self.stats["missing_abstract"] = sum(1 for p in papers.values() if not p["abstract"])
        self._write_unresolved()
        log.info("normalize stats: %s", dict(self.stats))
        return {"papers": list(papers.values()), "authors": list(authors.values()),
                "institutions": list(insts.values()), "venues": list(venues.values()),
                "paper_authors": paper_authors, "affiliations": affiliations, "citations": citations}

    def _write_unresolved(self) -> None:
        REJECTED.mkdir(parents=True, exist_ok=True)
        with open(REJECTED / "unresolved.csv", "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["kind", "ref", "detail"])
            w.writeheader()
            w.writerows(self.unresolved)
