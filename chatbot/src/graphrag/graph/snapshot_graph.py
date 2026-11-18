"""Read-only repository over the verified offline snapshot (JSONL), not over Neo4j.

Purpose:
1. Independent oracle: it re-implements the 12 catalog actions in plain Python from the
   offline tables, so dataset answers and Cypher results can be cross-checked.
2. Local evaluation of the REAL LLM on REAL data when Aura is unreachable. Responses are
   labelled `graph=snapshot`; this is never evidence for the Aura gate (G4).

Rows have exactly the same shape and ordering as the Cypher templates in cypher_templates.py.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from graphrag.graph.base import EntityRecord, GraphQueryResult
from graphrag.models import QueryAction, QueryStep

DEFAULT_SNAPSHOT_DIR = Path(__file__).resolve().parents[4] / "offline" / "data"
TOPIC_NAMES = {
    "llm": "Large language models",
    "mt": "Machine translation",
    "qa": "Question answering",
    "retrieval": "Retrieval and RAG",
    "summarization": "Summarization",
    "safety_eval": "Safety and LLM evaluation",
}
REL_TYPES = (
    "FIRST_AUTHOR_OF",
    "OTHER_AUTHOR_OF",
    "COAUTHORED_WITH",
    "AFFILIATED_WITH",
    "APPEARS_IN",
    "HAS_TOPIC",
    "CITES",
    "ORG_COAUTHORED_WITH",
    "RESEARCHES",
    "ACTIVE_IN",
)
MAX_PATH_HOPS = 4


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _desc(value: Any) -> Any:
    """Sort key helper: invert numbers for DESC order."""
    return -value if isinstance(value, int | float) else value


class SnapshotGraphRepository:
    name = "snapshot"

    def __init__(self, snapshot_dir: Path = DEFAULT_SNAPSHOT_DIR) -> None:
        processed = snapshot_dir / "processed"
        derived = snapshot_dir / "derived"
        manifest_path = processed / "manifest.json"
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.snapshot_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

        self.papers = {row["id"]: row for row in _read_jsonl(processed / "papers.jsonl")}
        self.authors = {row["id"]: row for row in _read_jsonl(processed / "authors.jsonl")}
        self.institutions = {row["id"]: row for row in _read_jsonl(processed / "institutions.jsonl")}
        self.venues = {row["id"]: row for row in _read_jsonl(processed / "venues.jsonl")}
        self.topics = {
            f"topic:{key}": {"id": f"topic:{key}", "name": name} for key, name in TOPIC_NAMES.items()
        }
        self.edges: dict[str, list[dict[str, Any]]] = {
            rel: _read_jsonl(derived / f"edges_{rel}.jsonl") for rel in REL_TYPES
        }

        self.out_edges: dict[str, dict[str, list[dict[str, Any]]]] = {
            rel: defaultdict(list) for rel in REL_TYPES
        }
        self.in_edges: dict[str, dict[str, list[dict[str, Any]]]] = {
            rel: defaultdict(list) for rel in REL_TYPES
        }
        for rel, rows in self.edges.items():
            for edge in rows:
                self.out_edges[rel][edge["from"]].append(edge)
                self.in_edges[rel][edge["to"]].append(edge)

    # ---- repository protocol -------------------------------------------------------------
    async def entity_catalog(self, *, force_refresh: bool = False) -> list[EntityRecord]:
        _ = force_refresh
        records: list[EntityRecord] = []
        for paper in self.papers.values():
            records.append(
                EntityRecord(id=paper["id"], label="Paper", name=paper.get("title") or paper["id"])
            )
        for author in self.authors.values():
            records.append(
                EntityRecord(
                    id=author["id"],
                    label="Author",
                    name=author.get("name") or author["id"],
                    identity_status=author.get("identity_status"),
                )
            )
        for inst in self.institutions.values():
            records.append(
                EntityRecord(id=inst["id"], label="Institution", name=inst.get("name") or inst["id"])
            )
        for venue in self.venues.values():
            records.append(EntityRecord(id=venue["id"], label="Venue", name=venue.get("name") or venue["id"]))
        for topic in self.topics.values():
            records.append(EntityRecord(id=topic["id"], label="Topic", name=topic["name"]))
        return records

    async def execute(self, step: QueryStep) -> GraphQueryResult:
        rows = self.rows(step.action, step.params)
        limit = min(step.limit, 100)
        page = rows[step.offset : step.offset + limit]
        truncated = len(rows) > step.offset + limit
        return GraphQueryResult(records=page, truncated=truncated, total=len(rows))

    async def health(self) -> tuple[bool, str]:
        return True, f"local snapshot (not Aura); manifest sha256 {self.snapshot_hash[:12]}"

    async def preview(self) -> dict[str, Any]:
        return {
            "nodes": {
                "Paper": len(self.papers),
                "Author": len(self.authors),
                "Institution": len(self.institutions),
                "Venue": len(self.venues),
                "Topic": len(self.topics),
            },
            "relationships": {rel: len(rows) for rel, rows in self.edges.items()},
            "scope_id": self.manifest.get("scope_id"),
            "source": "local_snapshot",
        }

    async def close(self) -> None:
        return None

    # ---- the 12 actions (same row shape/order as the Cypher catalog) ------------------------
    def rows(self, action: QueryAction, params: dict[str, Any]) -> list[dict[str, Any]]:
        handlers = {
            QueryAction.AUTHOR_PAPERS: self._author_papers,
            QueryAction.COAUTHORS: self._coauthors,
            QueryAction.SHARED_PAPERS: self._shared_papers,
            QueryAction.AUTHOR_AFFILIATIONS: self._author_affiliations,
            QueryAction.COAUTHOR_AFFILIATIONS: self._coauthor_affiliations,
            QueryAction.PAPER_AUTHORS: self._paper_authors,
            QueryAction.TOPIC_PAPERS: self._topic_papers,
            QueryAction.PAPER_VENUE: self._paper_venue,
            QueryAction.PAPER_CITATIONS: self._paper_citations,
            QueryAction.ORG_COLLABORATIONS: self._org_collaborations,
            QueryAction.AUTHOR_PATH: self._author_path,
            QueryAction.NETWORK_TOP: self._network_top,
        }
        return handlers[action](params)

    def _source(self, paper_id: str) -> dict[str, Any]:
        paper = self.papers[paper_id]
        return {"paper_id": paper_id, "title": paper["title"], "url": paper["source_url"]}

    def _paper_row(
        self, subject: str, predicate: str, paper_id: str, value: dict[str, Any], object_id: str | None = None
    ) -> dict[str, Any]:
        paper = self.papers[paper_id]
        return {
            "subject_id": subject,
            "predicate": predicate,
            "object_id": object_id or paper_id,
            "value": {**value, "sources": [self._source(paper_id)]},
            "paper_ids": [paper_id],
            "source_url": paper["source_url"],
            "year": paper["year"],
            "title": paper["title"],
        }

    @staticmethod
    def _in_years(year: int, params: dict[str, Any]) -> bool:
        year_from, year_to = params.get("year_from"), params.get("year_to")
        if year_from is not None and year < year_from:
            return False
        return not (year_to is not None and year > year_to)

    def _undirected(self, rel: str, node_id: str) -> list[tuple[str, dict[str, Any]]]:
        pairs = [(edge["to"], edge) for edge in self.out_edges[rel].get(node_id, [])]
        pairs += [(edge["from"], edge) for edge in self.in_edges[rel].get(node_id, [])]
        return pairs

    def _author_papers(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        author_id = params["author_id"]
        rows = []
        for rel in ("FIRST_AUTHOR_OF", "OTHER_AUTHOR_OF"):
            for edge in self.out_edges[rel].get(author_id, []):
                paper = self.papers[edge["to"]]
                if not self._in_years(paper["year"], params):
                    continue
                rows.append(
                    self._paper_row(
                        author_id,
                        "AUTHORED",
                        paper["id"],
                        {"title": paper["title"], "name": paper["title"], "position": edge.get("position")},
                    )
                )
        return sorted(rows, key=lambda row: (_desc(row["year"]), row["title"]))

    def _coauthors(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        author_id = params["author_id"]
        rows = []
        for other_id, edge in self._undirected("COAUTHORED_WITH", author_id):
            rows.append(
                {
                    "subject_id": author_id,
                    "predicate": "COAUTHORED_WITH",
                    "object_id": other_id,
                    "value": {
                        "name": self.authors[other_id]["name"],
                        "shared_count": edge["shared_count"],
                        "sources": [self._source(pid) for pid in edge["evidence_paper_ids"]],
                    },
                    "paper_ids": edge["evidence_paper_ids"],
                    "source_url": None,
                    "year": edge["last_year"],
                    "title": None,
                }
            )
        return sorted(rows, key=lambda row: (-row["value"]["shared_count"], row["value"]["name"]))

    def _coauthor_edge(self, a: str, b: str) -> dict[str, Any] | None:
        for other_id, edge in self._undirected("COAUTHORED_WITH", a):
            if other_id == b:
                return edge
        return None

    def _shared_papers(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        a, b = params["author_id"], params["other_author_id"]
        edge = self._coauthor_edge(a, b)
        if edge is None:
            return []
        rows = [
            self._paper_row(
                a,
                "SHARED_PAPER_WITH",
                pid,
                {"name": self.papers[pid]["title"], "title": self.papers[pid]["title"]},
                object_id=b,
            )
            for pid in edge["evidence_paper_ids"]
        ]
        return sorted(rows, key=lambda row: (_desc(row["year"]), row["title"]))

    def _author_affiliations(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        author_id = params["author_id"]
        rows = []
        for edge in self.out_edges["AFFILIATED_WITH"].get(author_id, []):
            inst = self.institutions[edge["to"]]
            for pid in edge["evidence_paper_ids"]:
                rows.append(
                    self._paper_row(
                        author_id,
                        "AFFILIATED_WITH_ON_PAPER",
                        pid,
                        {"name": inst["name"], "paper_title": self.papers[pid]["title"]},
                        object_id=inst["id"],
                    )
                )
        return sorted(rows, key=lambda row: (_desc(row["year"]), row["value"]["name"]))

    def _coauthor_affiliations(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        author_id = params["author_id"]
        rows = []
        for other_id, co_edge in self._undirected("COAUTHORED_WITH", author_id):
            co_papers = co_edge["evidence_paper_ids"]
            for af_edge in self.out_edges["AFFILIATED_WITH"].get(other_id, []):
                inst = self.institutions[af_edge["to"]]
                for pid in [pid for pid in co_papers if pid in af_edge["evidence_paper_ids"]]:
                    rows.append(
                        self._paper_row(
                            author_id,
                            "COAUTHOR_AFFILIATION_ON_SHARED_PAPER",
                            pid,
                            {
                                "name": inst["name"],
                                "coauthor_id": other_id,
                                "coauthor_name": self.authors[other_id]["name"],
                                "paper_title": self.papers[pid]["title"],
                            },
                            object_id=inst["id"],
                        )
                    )
        return sorted(
            rows, key=lambda row: (_desc(row["year"]), row["value"]["coauthor_name"], row["value"]["name"])
        )

    def _paper_authors(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        paper_id = params["paper_id"]
        rows = []
        for rel in ("FIRST_AUTHOR_OF", "OTHER_AUTHOR_OF"):
            for edge in self.in_edges[rel].get(paper_id, []):
                author = self.authors[edge["from"]]
                rows.append(
                    self._paper_row(
                        paper_id,
                        rel,
                        paper_id,
                        {"name": author["name"], "position": edge.get("position")},
                        object_id=author["id"],
                    )
                )
        return sorted(rows, key=lambda row: row["value"]["position"])

    def _topic_papers(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        topic_id = params["topic_id"]
        rows = []
        for edge in self.in_edges["HAS_TOPIC"].get(topic_id, []):
            paper = self.papers[edge["from"]]
            if not self._in_years(paper["year"], params):
                continue
            rows.append(
                self._paper_row(
                    topic_id,
                    "HAS_LABELLED_PAPER",
                    paper["id"],
                    {"name": paper["title"], "title": paper["title"], "rule_id": edge.get("rule_id")},
                )
            )
        return sorted(rows, key=lambda row: (_desc(row["year"]), row["title"]))

    def _paper_venue(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        paper_id = params["paper_id"]
        rows = []
        for edge in self.out_edges["APPEARS_IN"].get(paper_id, []):
            venue = self.venues[edge["to"]]
            rows.append(
                self._paper_row(
                    paper_id,
                    "APPEARS_IN",
                    paper_id,
                    {"name": venue["name"], "kind": venue.get("kind")},
                    object_id=venue["id"],
                )
            )
        return rows

    def _paper_citations(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        paper_id = params["paper_id"]
        direction = params.get("direction", "both")
        rows = []
        if direction in {"outgoing", "both"}:
            for edge in self.out_edges["CITES"].get(paper_id, []):
                other = self.papers[edge["to"]]
                rows.append(self._citation_row(paper_id, other, "CITES_IN_CORPUS"))
        if direction in {"incoming", "both"}:
            for edge in self.in_edges["CITES"].get(paper_id, []):
                other = self.papers[edge["from"]]
                rows.append(self._citation_row(paper_id, other, "CITED_BY_IN_CORPUS"))
        return sorted(rows, key=lambda row: (_desc(row["year"]), row["title"]))

    def _citation_row(self, anchor: str, other: dict[str, Any], relation: str) -> dict[str, Any]:
        return {
            "subject_id": anchor,
            "predicate": relation,
            "object_id": other["id"],
            "value": {
                "name": other["title"],
                "title": other["title"],
                "sources": [self._source(other["id"])],
            },
            "paper_ids": [other["id"]],
            "source_url": other["source_url"],
            "year": other["year"],
            "title": other["title"],
        }

    def _org_collaborations(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        inst_id = params["institution_id"]
        rows = []
        for other_id, edge in self._undirected("ORG_COAUTHORED_WITH", inst_id):
            rows.append(
                {
                    "subject_id": inst_id,
                    "predicate": "ORG_COAUTHORED_WITH",
                    "object_id": other_id,
                    "value": {
                        "name": self.institutions[other_id]["name"],
                        "shared_count": edge["shared_count"],
                        "sources": [self._source(pid) for pid in edge["evidence_paper_ids"]],
                    },
                    "paper_ids": edge["evidence_paper_ids"],
                    "source_url": None,
                    "year": edge["last_year"],
                    "title": None,
                }
            )
        return sorted(rows, key=lambda row: (-row["value"]["shared_count"], row["value"]["name"]))

    def shortest_hops(self, a: str, b: str) -> int | None:
        """BFS hop count over COAUTHORED_WITH (undirected), bounded by MAX_PATH_HOPS."""
        path = self._shortest_path(a, b)
        return None if path is None else len(path) - 1

    def _shortest_path(self, a: str, b: str) -> list[str] | None:
        if a == b:
            return None
        parent: dict[str, str | None] = {a: None}
        frontier = deque([(a, 0)])
        while frontier:
            node, depth = frontier.popleft()
            if depth >= MAX_PATH_HOPS:
                continue
            for other, _ in sorted(self._undirected("COAUTHORED_WITH", node)):
                if other in parent:
                    continue
                parent[other] = node
                if other == b:
                    path = [b]
                    while parent[path[-1]] is not None:
                        path.append(parent[path[-1]])  # type: ignore[arg-type]
                    return list(reversed(path))
                frontier.append((other, depth + 1))
        return None

    def _author_path(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        a, b = params["author_id"], params["other_author_id"]
        path = self._shortest_path(a, b)
        if path is None:
            return []
        paper_ids: list[str] = []
        for left, right in zip(path, path[1:], strict=False):
            edge = self._coauthor_edge(left, right)
            for pid in edge["evidence_paper_ids"] if edge else []:
                if pid not in paper_ids:
                    paper_ids.append(pid)
        return [
            {
                "subject_id": a,
                "predicate": "COAUTHOR_PATH",
                "object_id": b,
                "value": {
                    "name": self.authors[b]["name"],
                    "author_ids": path,
                    "author_names": [self.authors[node]["name"] for node in path],
                    "hop_count": len(path) - 1,
                    "sources": [self._source(pid) for pid in paper_ids],
                },
                "paper_ids": paper_ids,
                "source_url": None,
                "year": None,
                "title": None,
            }
        ]

    def coauthor_counts(self) -> dict[str, int]:
        neighbours: dict[str, set[str]] = defaultdict(set)
        for edge in self.edges["COAUTHORED_WITH"]:
            neighbours[edge["from"]].add(edge["to"])
            neighbours[edge["to"]].add(edge["from"])
        return {author_id: len(others) for author_id, others in neighbours.items()}

    def _network_top(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        _ = params
        shared_sum: dict[str, int] = defaultdict(int)
        for edge in self.edges["COAUTHORED_WITH"]:
            shared_sum[edge["from"]] += edge["shared_count"]
            shared_sum[edge["to"]] += edge["shared_count"]
        rows = []
        for author_id, count in self.coauthor_counts().items():
            rows.append(
                {
                    "subject_id": "network",
                    "predicate": "RANKED_BY_COAUTHOR_COUNT",
                    "object_id": author_id,
                    "value": {
                        "name": self.authors[author_id]["name"],
                        "metric": "distinct_coauthor_count",
                        "metric_value": count,
                        "shared_paper_edge_sum": shared_sum[author_id],
                        "sources": [],
                    },
                    "paper_ids": [],
                    "source_url": None,
                    "year": None,
                    "title": None,
                }
            )
        return sorted(rows, key=lambda row: (-row["value"]["metric_value"], row["value"]["name"]))
