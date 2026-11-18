"""Large, source-backed QA candidate set built from the verified graph snapshot.

Pipeline (all deterministic for a given --seed and snapshot hash):
1. Split assignment BEFORE question generation: every anchor entity (author, paper,
   institution, topic) is hashed to train/val/test. Two-entity questions only pair
   entities of the same split, so no anchor entity ever crosses splits.
2. Candidates: for each catalog action, questions are written from several templates
   (vi/en, year filters, title variants) over REAL entities in the snapshot. The expected
   answer comes from `SnapshotGraphRepository` (same row semantics as the Cypher catalog).
3. Silver validation: each expected answer is recomputed by `IndependentOracle`, which reads
   only the raw processed tables (paper_authors, affiliations, citations, paper_topics) and
   never the derived edge files. Agreement => `silver_validated`; disagreement => rejected
   with a reason. Silver is NOT human gold.
4. Negative (verified-absent names), out-of-scope and clarify cases are generated separately
   and labelled by kind.
5. Dedup on (normalized question, action, params); leakage checker must pass.

Outputs (under --out-dir):
  generated/candidates_large.jsonl     every generated candidate (pre-validation)
  reviewed/silver_validated.jsonl      passed independent oracle check
  reviewed/rejected_silver.jsonl       failed check, with reason
  splits/{train,val,test}.jsonl        silver cases by split
  splits/manifest.json                 hashes, counts, distributions, leakage result
  splits/dataset_quality_audit.md      human-readable audit
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import unicodedata
from collections import Counter, defaultdict, deque
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import Any

from datasets.schema import (
    EntityMention,
    ExpectedCitations,
    ExpectedFacts,
    ExpectedQuery,
    QuestionCase,
    ReviewStatus,
)
from graphrag.graph.snapshot_graph import MAX_PATH_HOPS, SnapshotGraphRepository
from graphrag.models import QueryAction

PAGE_SIZE = 20
MAX_CLIQUE_AUTHORS = 20  # mirrors offline derive.py: larger author lists are not cliqued
SPLIT_CUTS = (70, 85)  # hash bucket < 70 train, < 85 val, else test

TEMPLATES: dict[QueryAction, list[tuple[str, str]]] = {
    QueryAction.AUTHOR_PAPERS: [
        ("vi", "{a} có những bài báo nào trong corpus?"),
        ("vi", "Liệt kê các bài báo của tác giả {a}."),
        ("en", "Which papers did {a} write in this dataset?"),
    ],
    QueryAction.COAUTHORS: [
        ("vi", "Đồng tác giả của {a} là ai?"),
        ("vi", "{a} đã viết chung với những ai?"),
        ("en", "Who are the co-authors of {a}?"),
    ],
    QueryAction.SHARED_PAPERS: [
        ("vi", "{a} và {b} có bài báo chung nào?"),
        ("en", "Which papers did {a} and {b} write together?"),
    ],
    QueryAction.AUTHOR_AFFILIATIONS: [
        ("vi", "{a} gắn với tổ chức nào theo từng bài báo?"),
        ("en", "Which institutions is {a} affiliated with on their papers?"),
    ],
    QueryAction.COAUTHOR_AFFILIATIONS: [
        ("vi", "Tổ chức của các đồng tác giả của {a} trên bài chung là gì?"),
    ],
    QueryAction.PAPER_AUTHORS: [
        ("vi", "Ai là tác giả của bài “{p}”?"),
        ("en", "Who wrote the paper “{p}”?"),
    ],
    QueryAction.TOPIC_PAPERS: [
        ("vi", "Các bài báo thuộc chủ đề {t} là gì?"),
        ("en", "List papers labelled with the topic {t}."),
    ],
    QueryAction.PAPER_VENUE: [
        ("vi", "Bài “{p}” được đăng ở venue nào?"),
        ("en", "In which venue did “{p}” appear?"),
    ],
    QueryAction.PAPER_CITATIONS: [
        ("vi", "Bài “{p}” có quan hệ trích dẫn với bài nào trong corpus?"),
    ],
    QueryAction.ORG_COLLABORATIONS: [
        ("vi", "{i} hợp tác với những tổ chức nào trong corpus?"),
        ("en", "Which institutions collaborated with {i}?"),
    ],
    QueryAction.AUTHOR_PATH: [
        ("vi", "Đường đồng tác giả ngắn nhất giữa {a} và {b} là gì?"),
        ("en", "How are {a} and {b} connected through co-authorship?"),
    ],
    QueryAction.NETWORK_TOP: [
        ("vi", "Top tác giả có nhiều đồng tác giả nhất là ai?"),
        ("en", "Which authors have the most distinct co-authors?"),
        ("vi", "Xếp hạng tác giả theo số đồng tác giả."),
    ],
}
YEAR_TEMPLATES = {
    QueryAction.AUTHOR_PAPERS: ("vi", "{a} có những bài báo nào năm {y}?"),
    QueryAction.TOPIC_PAPERS: ("vi", "Các bài báo chủ đề {t} năm {y}?"),
}
OUT_OF_SCOPE = [
    "Đặt phòng họp ngày mai lúc {h} giờ",
    "Thời tiết ở {c} hôm nay thế nào?",
    "Cách nấu phở bò?",
    "Book a meeting room for {h} pm tomorrow",
    "What's the weather in {c}?",
    "Viết giúp tôi email xin nghỉ phép",
    "Giá vàng hôm nay bao nhiêu?",
    "Recommend a good movie tonight",
    "Dịch câu 'hello' sang tiếng Pháp",
    "Tỷ số trận bóng tối qua?",
]
CITIES = ["Hà Nội", "Đà Nẵng", "Paris", "Tokyo", "Seoul", "Berlin", "Toronto", "Sydney"]
CLARIFY = [
    ("vi", "Các bài báo của tác giả đó?", "author_papers"),
    ("vi", "Đồng tác giả của người ấy là ai?", "coauthors"),
    ("en", "What did they publish?", "author_papers"),
    ("vi", "Bài báo đó đăng ở đâu?", "paper_venue"),
    ("vi", "Ai viết bài đó?", "paper_authors"),
    ("en", "Which institutions does that author belong to?", "author_affiliations"),
]


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text)).strip()


def split_of(entity_id: str, seed: int) -> str:
    bucket = int(hashlib.sha256(f"{seed}:{entity_id}".encode()).hexdigest(), 16) % 100
    if bucket < SPLIT_CUTS[0]:
        return "train"
    if bucket < SPLIT_CUTS[1]:
        return "val"
    return "test"


class IndependentOracle:
    """Recomputes answers from raw processed tables only (never the derived edge files)."""

    def __init__(self, processed_dir: Path) -> None:
        def read(name: str) -> list[dict[str, Any]]:
            with (processed_dir / name).open(encoding="utf-8") as handle:
                return [json.loads(line) for line in handle if line.strip()]

        self.papers = {row["id"]: row for row in read("papers.jsonl")}
        self.authors_of: dict[str, dict[str, int]] = defaultdict(dict)
        self.papers_of: dict[str, set[str]] = defaultdict(set)
        for row in read("paper_authors.jsonl"):
            self.authors_of[row["paper_id"]][row["author_id"]] = row["position"]
            self.papers_of[row["author_id"]].add(row["paper_id"])
        self.affil = read("affiliations.jsonl")
        self.citations = read("citations.jsonl")
        self.topics = read("paper_topics.jsonl")
        self._coauthor_cache: dict[str, set[str]] = {}

    def _cliqued(self, paper_id: str) -> bool:
        return len(self.authors_of[paper_id]) <= MAX_CLIQUE_AUTHORS

    def coauthors(self, author_id: str) -> set[str]:
        cached = self._coauthor_cache.get(author_id)
        if cached is not None:
            return cached
        others: set[str] = set()
        for pid in self.papers_of[author_id]:
            if self._cliqued(pid):
                others |= set(self.authors_of[pid]) - {author_id}
        self._coauthor_cache[author_id] = others
        return others

    def answer(self, action: QueryAction, params: dict[str, Any]) -> list[str]:
        """Sorted set of object ids (or 'paper|object' keys) the action must return."""
        year_from, year_to = params.get("year_from"), params.get("year_to")

        def in_years(pid: str) -> bool:
            year = self.papers[pid]["year"]
            return (year_from is None or year >= year_from) and (year_to is None or year <= year_to)

        if action == QueryAction.AUTHOR_PAPERS:
            return sorted(pid for pid in self.papers_of[params["author_id"]] if in_years(pid))
        if action == QueryAction.COAUTHORS:
            return sorted(self.coauthors(params["author_id"]))
        if action == QueryAction.SHARED_PAPERS:
            shared = self.papers_of[params["author_id"]] & self.papers_of[params["other_author_id"]]
            return sorted(pid for pid in shared if self._cliqued(pid))
        if action == QueryAction.AUTHOR_AFFILIATIONS:
            return sorted(
                {
                    f"{r['paper_id']}|{r['institution_id']}"
                    for r in self.affil
                    if r["author_id"] == params["author_id"]
                }
            )
        if action == QueryAction.COAUTHOR_AFFILIATIONS:
            author_id = params["author_id"]
            keys = set()
            for r in self.affil:
                pid = r["paper_id"]
                if r["author_id"] != author_id and author_id in self.authors_of[pid] and self._cliqued(pid):
                    keys.add(f"{pid}|{r['institution_id']}|{r['author_id']}")
            return sorted(keys)
        if action == QueryAction.PAPER_AUTHORS:
            return sorted(self.authors_of[params["paper_id"]])
        if action == QueryAction.TOPIC_PAPERS:
            topic = params["topic_id"].removeprefix("topic:")
            return sorted(
                {r["paper_id"] for r in self.topics if r["topic_id"] == topic and in_years(r["paper_id"])}
            )
        if action == QueryAction.PAPER_VENUE:
            return [self.papers[params["paper_id"]]["venue_id"]]
        if action == QueryAction.PAPER_CITATIONS:
            pid = params["paper_id"]
            out = {f"out|{r['cited_paper_id']}" for r in self.citations if r["citing_paper_id"] == pid}
            inc = {f"in|{r['citing_paper_id']}" for r in self.citations if r["cited_paper_id"] == pid}
            return sorted(out | inc)
        if action == QueryAction.ORG_COLLABORATIONS:
            inst = params["institution_id"]
            by_paper: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
            for r in self.affil:
                by_paper[r["paper_id"]][r["author_id"]].add(r["institution_id"])
            partners = set()
            for amap in by_paper.values():
                for a1, a2 in combinations(sorted(amap), 2):
                    for i in amap[a1]:
                        for j in amap[a2]:
                            if i != j and inst in (i, j):
                                partners.add(j if i == inst else i)
            return sorted(partners)
        if action == QueryAction.AUTHOR_PATH:
            hops = self.hops(params["author_id"], params["other_author_id"])
            return [] if hops is None else [str(hops)]
        if action == QueryAction.NETWORK_TOP:
            counts = {author: len(self.coauthors(author)) for author in self.papers_of}
            ranked = sorted(
                (author for author, count in counts.items() if count > 0), key=lambda author: -counts[author]
            )
            return [str(counts[author]) for author in ranked[:PAGE_SIZE]]
        raise ValueError(action)

    def hops(self, a: str, b: str) -> int | None:
        seen = {a: 0}
        queue = deque([a])
        while queue:
            node = queue.popleft()
            if seen[node] >= MAX_PATH_HOPS:
                continue
            for other in self.coauthors(node):
                if other not in seen:
                    seen[other] = seen[node] + 1
                    if other == b:
                        return seen[other]
                    queue.append(other)
        return None


def snapshot_answer(rows: list[dict[str, Any]], action: QueryAction) -> list[str]:
    """Same key shape as IndependentOracle.answer, computed from snapshot rows."""
    if action in {QueryAction.AUTHOR_PAPERS, QueryAction.TOPIC_PAPERS, QueryAction.SHARED_PAPERS}:
        return sorted({row["paper_ids"][0] for row in rows})
    if action in {QueryAction.COAUTHORS, QueryAction.PAPER_AUTHORS, QueryAction.ORG_COLLABORATIONS}:
        return sorted({row["object_id"] for row in rows})
    if action == QueryAction.AUTHOR_AFFILIATIONS:
        return sorted({f"{row['paper_ids'][0]}|{row['object_id']}" for row in rows})
    if action == QueryAction.COAUTHOR_AFFILIATIONS:
        return sorted(
            {f"{row['paper_ids'][0]}|{row['object_id']}|{row['value']['coauthor_id']}" for row in rows}
        )
    if action == QueryAction.PAPER_VENUE:
        return [row["object_id"] for row in rows]
    if action == QueryAction.PAPER_CITATIONS:
        prefix = {"CITES_IN_CORPUS": "out", "CITED_BY_IN_CORPUS": "in"}
        return sorted({f"{prefix[row['predicate']]}|{row['object_id']}" for row in rows})
    if action == QueryAction.AUTHOR_PATH:
        return [str(rows[0]["value"]["hop_count"])] if rows else []
    if action == QueryAction.NETWORK_TOP:
        return [str(row["value"]["metric_value"]) for row in rows[:PAGE_SIZE]]
    raise ValueError(action)


class Builder:
    def __init__(self, repo: SnapshotGraphRepository, oracle: IndependentOracle, seed: int) -> None:
        self.repo = repo
        self.oracle = oracle
        self.seed = seed
        self.rng = random.Random(seed)
        self.snapshot_version = repo.snapshot_hash[:16]
        self.scope = repo.manifest.get("scope_id", "nlpgraph-v1")
        self.author_name_count = Counter(normalize(a["name"]) for a in repo.authors.values())
        self.institution_name_count = Counter(normalize(i["name"]) for i in repo.institutions.values())
        self.paper_title_count = Counter(normalize(p["title"]) for p in repo.papers.values())
        self.candidates: list[QuestionCase] = []

    # ---- helpers ------------------------------------------------------------------------------
    def _is_ambiguous(self, label: str, name: str) -> bool:
        counts = {
            "Author": self.author_name_count,
            "Institution": self.institution_name_count,
            "Paper": self.paper_title_count,
        }.get(label)
        return bool(counts) and counts[normalize(name)] > 1

    def add(
        self,
        action: QueryAction,
        params: dict[str, Any],
        question: str,
        language: str,
        mentions: list[tuple[str, str]],
        anchors: list[str],
        template_id: str,
        filters: dict[str, Any] | None = None,
    ) -> None:
        rows = self.repo.rows(action, params)
        if any(self._is_ambiguous(label, text) for text, label in mentions):
            status = "ambiguous"
        elif not rows:
            status = "not_found"
        elif len(rows) > PAGE_SIZE:
            status = "partial"
        else:
            status = "answered"
        citations = []
        for row in rows[:PAGE_SIZE]:
            for source in (row.get("value") or {}).get("sources", []):
                if source.get("paper_id") and source["paper_id"] not in citations:
                    citations.append(source["paper_id"])
        object_ids = [row["object_id"] for row in rows]
        split = split_of(anchors[0], self.seed) if anchors else split_of(question, self.seed)
        case_id = (
            "L-"
            + hashlib.sha256(
                f"{action}|{json.dumps(params, sort_keys=True)}|{question}".encode()
            ).hexdigest()[:16]
        )
        self.candidates.append(
            QuestionCase(
                case_id=case_id,
                question=question,
                language=language,  # type: ignore[arg-type]
                expected_status=status,  # type: ignore[arg-type]
                expected_query=ExpectedQuery(intent=action.value, entity_ids=anchors, params=params),
                expected_facts=ExpectedFacts(
                    predicates=sorted({row["predicate"] for row in rows}),
                    object_ids=object_ids,
                    answer="",
                ),
                expected_citations=ExpectedCitations(
                    paper_ids=citations,
                    source_urls=[
                        self.repo.papers[pid]["source_url"] for pid in citations if pid in self.repo.papers
                    ],
                ),
                entity_mentions=[EntityMention(text=text, type=label) for text, label in mentions],
                filters=filters or {},
                scope_id=self.scope,
                snapshot_version=self.snapshot_version,
                template_id=template_id,
                group_id=anchors[0] if anchors else f"global:{action.value}",
                seed=self.seed,
                review_status=ReviewStatus.NEEDS_REVIEW,
                split=split,  # type: ignore[arg-type]
                provenance={
                    "generator": "datasets.build_large",
                    "graph_source": "local_snapshot",
                    "snapshot_manifest_sha256": self.repo.snapshot_hash,
                    "total_results": len(rows),
                    "page_size": PAGE_SIZE,
                    "kind": "positive" if rows else "empty_result",
                },
            )
        )

    def _pick(self, action: QueryAction) -> tuple[str, str, str]:
        language, template = self.rng.choice(TEMPLATES[action])
        index = TEMPLATES[action].index((language, template))
        return language, template, f"{action.value}:t{index}"

    # ---- generators -------------------------------------------------------------------------
    def author_actions(self, per_action: int) -> None:
        authors = sorted(self.repo.authors.values(), key=lambda a: a["id"])
        self.rng.shuffle(authors)
        coauthor_counts = self.repo.coauthor_counts()
        affiliated = {edge["from"] for edge in self.repo.edges["AFFILIATED_WITH"]}
        for action, pool in (
            (QueryAction.AUTHOR_PAPERS, authors),
            (QueryAction.COAUTHORS, [a for a in authors if coauthor_counts.get(a["id"])]),
            (QueryAction.AUTHOR_AFFILIATIONS, [a for a in authors if a["id"] in affiliated]),
            (QueryAction.COAUTHOR_AFFILIATIONS, [a for a in authors if a["id"] in affiliated]),
        ):
            for author in pool[:per_action]:
                language, template, template_id = self._pick(action)
                params: dict[str, Any] = {"author_id": author["id"]}
                if action == QueryAction.AUTHOR_PAPERS:
                    params.update(year_from=None, year_to=None)
                self.add(
                    action,
                    params,
                    template.format(a=author["name"]),
                    language,
                    [(author["name"], "Author")],
                    [author["id"]],
                    template_id,
                )
        # year-filtered variants
        for author in authors[: per_action // 3]:
            years = sorted({self.repo.papers[pid]["year"] for pid in self.oracle.papers_of[author["id"]]})
            year = self.rng.choice(years)
            language, template = YEAR_TEMPLATES[QueryAction.AUTHOR_PAPERS]
            params = {"author_id": author["id"], "year_from": year, "year_to": year}
            self.add(
                QueryAction.AUTHOR_PAPERS,
                params,
                template.format(a=author["name"], y=year),
                language,
                [(author["name"], "Author")],
                [author["id"]],
                "author_papers:year",
                filters={"year_from": year, "year_to": year},
            )

    def pair_actions(self, per_action: int) -> None:
        coauthor_edges = sorted(self.repo.edges["COAUTHORED_WITH"], key=lambda e: (e["from"], e["to"]))
        self.rng.shuffle(coauthor_edges)
        made = 0
        for edge in coauthor_edges:
            a, b = edge["from"], edge["to"]
            if split_of(a, self.seed) != split_of(b, self.seed):
                continue  # keeps both anchors inside one split
            name_a, name_b = self.repo.authors[a]["name"], self.repo.authors[b]["name"]
            language, template, template_id = self._pick(QueryAction.SHARED_PAPERS)
            self.add(
                QueryAction.SHARED_PAPERS,
                {"author_id": a, "other_author_id": b},
                template.format(a=name_a, b=name_b),
                language,
                [(name_a, "Author"), (name_b, "Author")],
                [a, b],
                template_id,
            )
            made += 1
            if made >= per_action:
                break
        # multi-hop paths: pick a, walk 2-3 hops away inside the same split
        authors = sorted(self.repo.authors)
        self.rng.shuffle(authors)
        made = 0
        for start in authors:
            if made >= per_action:
                break
            target = self._walk(start, self.rng.choice([2, 3]))
            if target is None or split_of(start, self.seed) != split_of(target, self.seed):
                continue
            name_a, name_b = self.repo.authors[start]["name"], self.repo.authors[target]["name"]
            language, template, template_id = self._pick(QueryAction.AUTHOR_PATH)
            self.add(
                QueryAction.AUTHOR_PATH,
                {"author_id": start, "other_author_id": target},
                template.format(a=name_a, b=name_b),
                language,
                [(name_a, "Author"), (name_b, "Author")],
                [start, target],
                template_id,
            )
            made += 1

    def _walk(self, start: str, steps: int) -> str | None:
        node = start
        for _ in range(steps):
            neighbours = sorted(other for other, _ in self.repo._undirected("COAUTHORED_WITH", node))
            if not neighbours:
                return None
            node = self.rng.choice(neighbours)
        hops = self.repo.shortest_hops(start, node)
        return node if hops and hops >= 2 else None

    def paper_actions(self, per_action: int) -> None:
        papers = sorted(self.repo.papers.values(), key=lambda p: p["id"])
        self.rng.shuffle(papers)
        cited = {e["from"] for e in self.repo.edges["CITES"]} | {e["to"] for e in self.repo.edges["CITES"]}
        for action, pool in (
            (QueryAction.PAPER_AUTHORS, papers),
            (QueryAction.PAPER_VENUE, papers),
            (QueryAction.PAPER_CITATIONS, [p for p in papers if p["id"] in cited]),
        ):
            for paper in pool[:per_action]:
                language, template, template_id = self._pick(action)
                title = paper["title"]
                params: dict[str, Any] = {"paper_id": paper["id"]}
                if action == QueryAction.PAPER_CITATIONS:
                    params["direction"] = "both"
                self.add(
                    action,
                    params,
                    template.format(p=title),
                    language,
                    [(title, "Paper")],
                    [paper["id"]],
                    template_id,
                )
            # title variant: lower-cased title tests normalization in entity linking
            for paper in pool[: max(1, per_action // 5)]:
                language, template, _ = self._pick(action)
                params = {"paper_id": paper["id"]}
                if action == QueryAction.PAPER_CITATIONS:
                    params["direction"] = "both"
                self.add(
                    action,
                    params,
                    template.format(p=paper["title"].lower()),
                    language,
                    [(paper["title"].lower(), "Paper")],
                    [paper["id"]],
                    f"{action.value}:lowercase_title",
                )

    def topic_and_org_actions(self, per_action: int) -> None:
        for topic_id, name in sorted(self.repo.topics.items()):
            for language, template in TEMPLATES[QueryAction.TOPIC_PAPERS]:
                self.add(
                    QueryAction.TOPIC_PAPERS,
                    {"topic_id": topic_id, "year_from": None, "year_to": None},
                    template.format(t=name["name"]),
                    language,
                    [(name["name"], "Topic")],
                    [topic_id],
                    "topic_papers:base",
                )
            for year in (2023, 2024, 2025):
                language, template = YEAR_TEMPLATES[QueryAction.TOPIC_PAPERS]
                self.add(
                    QueryAction.TOPIC_PAPERS,
                    {"topic_id": topic_id, "year_from": year, "year_to": year},
                    template.format(t=name["name"], y=year),
                    language,
                    [(name["name"], "Topic")],
                    [topic_id],
                    "topic_papers:year",
                    filters={"year_from": year, "year_to": year},
                )
        with_org = sorted(
            {e["from"] for e in self.repo.edges["ORG_COAUTHORED_WITH"]}
            | {e["to"] for e in self.repo.edges["ORG_COAUTHORED_WITH"]}
        )
        self.rng.shuffle(with_org)
        for inst_id in with_org[:per_action]:
            name = self.repo.institutions[inst_id]["name"]
            language, template, template_id = self._pick(QueryAction.ORG_COLLABORATIONS)
            self.add(
                QueryAction.ORG_COLLABORATIONS,
                {"institution_id": inst_id},
                template.format(i=name),
                language,
                [(name, "Institution")],
                [inst_id],
                template_id,
            )
        for language, template in TEMPLATES[QueryAction.NETWORK_TOP]:
            self.add(QueryAction.NETWORK_TOP, {}, template, language, [], [], "network_top:base")

    def negatives(self, count: int) -> list[QuestionCase]:
        """Names verified absent from the catalog (first + last name recombination)."""
        names = [a["name"].split() for a in self.repo.authors.values() if len(a["name"].split()) >= 2]
        firsts = sorted({parts[0] for parts in names})
        lasts = sorted({parts[-1] for parts in names})
        known = set(self.author_name_count)
        cases: list[QuestionCase] = []
        attempts = 0
        while len(cases) < count and attempts < count * 50:
            attempts += 1
            name = f"{self.rng.choice(firsts)} {self.rng.choice(lasts)}"
            if normalize(name) in known:
                continue
            known.add(normalize(name))
            language, template, _ = self._pick(QueryAction.AUTHOR_PAPERS)
            question = template.format(a=name)
            cases.append(
                self._special(
                    question,
                    language,
                    "not_found",
                    "author_papers",
                    [EntityMention(text=name, type="Author")],
                    "negative:absent_author",
                    {"verified_absent": True},
                )
            )
        return cases

    def out_of_scope(self) -> list[QuestionCase]:
        cases = []
        for template in OUT_OF_SCOPE:
            for value in range(3):
                question = template.format(h=7 + value, c=CITIES[(value * 3) % len(CITIES)])
                language = "en" if re.search(r"\b(the|a|for|what|recommend)\b", question.casefold()) else "vi"
                cases.append(
                    self._special(question, language, "out_of_scope", "unknown", [], "out_of_scope", {})
                )
        return cases

    def clarify(self) -> list[QuestionCase]:
        return [
            self._special(q, lang, "clarify", intent, [], "clarify:pronoun_no_history", {})
            for lang, q, intent in CLARIFY
        ]

    def _special(
        self,
        question: str,
        language: str,
        status: str,
        intent: str,
        mentions: list[EntityMention],
        template_id: str,
        extra: dict[str, Any],
    ) -> QuestionCase:
        case_id = "S-" + hashlib.sha256(f"{template_id}|{question}".encode()).hexdigest()[:16]
        return QuestionCase(
            case_id=case_id,
            question=question,
            language=language,  # type: ignore[arg-type]
            expected_status=status,  # type: ignore[arg-type]
            expected_query=ExpectedQuery(intent=intent, entity_ids=[], params={}),
            entity_mentions=mentions,
            scope_id=self.scope,
            snapshot_version=self.snapshot_version,
            template_id=template_id,
            group_id=f"special:{case_id}",
            seed=self.seed,
            review_status=ReviewStatus.NEEDS_REVIEW,
            split=split_of(case_id, self.seed),  # type: ignore[arg-type]
            provenance={"generator": "datasets.build_large", "kind": template_id.split(":")[0], **extra},
        )


def validate_silver(
    case: QuestionCase, repo: SnapshotGraphRepository, oracle: IndependentOracle
) -> str | None:
    """None when the independent oracle agrees; otherwise the rejection reason."""
    kind = case.provenance.get("kind")
    if kind in {"out_of_scope", "clarify"}:
        return None
    if kind == "negative":
        name = case.entity_mentions[0].text
        absent = all(normalize(author["name"]) != normalize(name) for author in repo.authors.values())
        return None if absent else "negative_name_exists"
    action = QueryAction(case.expected_query.intent)
    params = case.expected_query.params
    expected = snapshot_answer(repo.rows(action, params), action)
    independent = oracle.answer(action, params)
    if expected != independent:
        return f"oracle_mismatch:{len(expected)}vs{len(independent)}"
    if case.expected_status == "not_found" and kind == "positive":
        return "positive_without_results"
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out-dir", type=Path, default=Path("data"))
    parser.add_argument("--per-action", type=int, default=1300)
    parser.add_argument("--negatives", type=int, default=400)
    parser.add_argument("--seed", type=int, default=20261118)
    args = parser.parse_args()

    repo = SnapshotGraphRepository()
    oracle = IndependentOracle(Path(__file__).resolve().parents[2] / "offline" / "data" / "processed")
    builder = Builder(repo, oracle, args.seed)
    builder.author_actions(args.per_action)
    builder.pair_actions(args.per_action)
    builder.paper_actions(args.per_action)
    builder.topic_and_org_actions(args.per_action)
    specials = builder.negatives(args.negatives) + builder.out_of_scope() + builder.clarify()

    # dedup on the normalized question text: one input must have exactly one expected output
    # (same-name authors / same-title papers produce identical questions with different anchors)
    seen: set[str] = set()
    candidates: list[QuestionCase] = []
    duplicates = 0
    for case in builder.candidates + specials:
        key = normalize(case.question)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        candidates.append(case)

    silver: list[QuestionCase] = []
    rejected: list[dict[str, Any]] = []
    for case in candidates:
        reason = validate_silver(case, repo, oracle)
        if reason is None:
            silver.append(case.model_copy(update={"review_status": ReviewStatus.SILVER_VALIDATED}))
        else:
            rejected.append({"case_id": case.case_id, "reason": reason, "question": case.question})

    # leakage: an anchor entity may live in exactly one split
    entity_splits: dict[str, set[str]] = defaultdict(set)
    for case in silver:
        for entity_id in case.expected_query.entity_ids:
            entity_splits[entity_id].add(case.split or "")
    leaked = {key: sorted(value) for key, value in entity_splits.items() if len(value) > 1}
    question_splits: dict[str, set[str]] = defaultdict(set)
    for case in silver:
        question_splits[normalize(case.question)].add(case.split or "")
    leaked_questions = [key for key, value in question_splits.items() if len(value) > 1]

    out = args.out_dir
    _write(out / "generated" / "candidates_large.jsonl", candidates)
    _write(out / "reviewed" / "silver_validated.jsonl", silver)
    (out / "reviewed").mkdir(parents=True, exist_ok=True)
    with (out / "reviewed" / "rejected_silver.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for row in rejected:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    split_paths = {}
    for split in ("train", "val", "test"):
        rows = [case for case in silver if case.split == split]
        split_paths[split] = _write(out / "splits" / f"{split}.jsonl", rows)

    manifest = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "generator": "datasets.build_large",
        "seed": args.seed,
        "per_action": args.per_action,
        "graph_source": "local_snapshot (offline/data/processed + derived), NOT live Aura",
        "snapshot_manifest_sha256": repo.snapshot_hash,
        "counts": {
            "candidates": len(candidates),
            "duplicates_removed": duplicates,
            "silver_validated": len(silver),
            "rejected": len(rejected),
            "human_gold": 0,
        },
        "review_status_meaning": {
            "silver_validated": (
                "expected answer re-derived by an independent raw-table oracle; NOT human reviewed"
            ),
        },
        "per_intent": dict(Counter(case.expected_query.intent for case in silver)),
        "per_status": dict(Counter(case.expected_status for case in silver)),
        "per_language": dict(Counter(case.language for case in silver)),
        "per_template": dict(Counter(case.template_id for case in silver)),
        "per_split": {split: info["count"] for split, info in split_paths.items()},
        "per_split_intent": {
            split: dict(Counter(c.expected_query.intent for c in silver if c.split == split))
            for split in ("train", "val", "test")
        },
        "rejection_reasons": dict(Counter(row["reason"].split(":")[0] for row in rejected)),
        "leakage": {
            "anchor_entities_in_multiple_splits": len(leaked),
            "questions_in_multiple_splits": len(leaked_questions),
            "verdict": "PASS" if not leaked and not leaked_questions else "FAIL",
        },
        "files": {split: info for split, info in split_paths.items()},
    }
    (out / "splits" / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    _write_audit(out / "splits" / "dataset_quality_audit.md", manifest, silver)
    print(json.dumps({k: manifest[k] for k in ("counts", "per_split", "leakage")}, ensure_ascii=False))
    if leaked or leaked_questions:
        raise SystemExit("split leakage detected")


def _write(path: Path, rows: list[QuestionCase]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(row.model_dump_json() + "\n")
    return {
        "path": str(path).replace("\\", "/"),
        "count": len(rows),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _write_audit(path: Path, manifest: dict[str, Any], silver: list[QuestionCase]) -> None:
    lines = [
        "# Dataset quality audit (generated)",
        "",
        f"- Created: {manifest['created_at_utc']}",
        f"- Graph source: {manifest['graph_source']}",
        f"- Snapshot manifest sha256: `{manifest['snapshot_manifest_sha256']}`",
        f"- Candidates: {manifest['counts']['candidates']} (duplicates removed: "
        f"{manifest['counts']['duplicates_removed']})",
        f"- Silver validated (independent raw-table oracle agreed): {manifest['counts']['silver_validated']}",
        f"- Rejected: {manifest['counts']['rejected']} — reasons {manifest['rejection_reasons']}",
        "- Human/independent gold: **0** (no reviewer in this run; G6 cannot PASS on silver alone)",
        f"- Leakage check: **{manifest['leakage']['verdict']}** {manifest['leakage']}",
        "",
        "## Per intent",
        "",
        "| intent | silver | train | val | test |",
        "|---|---|---|---|---|",
    ]
    for intent, count in sorted(manifest["per_intent"].items()):
        per = [manifest["per_split_intent"][s].get(intent, 0) for s in ("train", "val", "test")]
        lines.append(f"| {intent} | {count} | {per[0]} | {per[1]} | {per[2]} |")
    lines += ["", "## Per expected status", ""]
    lines += [f"- {key}: {value}" for key, value in sorted(manifest["per_status"].items())]
    lines += ["", "## Random sample (10 silver cases, seed-fixed)", ""]
    sample = random.Random(7).sample(silver, min(10, len(silver)))
    for case in sample:
        lines.append(
            f"- `{case.case_id}` [{case.split}/{case.expected_status}] {case.question} → "
            f"{len(case.expected_facts.object_ids)} result(s)"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
