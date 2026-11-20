"""Small evidence-consistent synthetic graph implementing every query action."""

from __future__ import annotations

from typing import Any

from graphrag.graph.base import EntityRecord, GraphQueryResult
from graphrag.models import QueryAction, QueryStep


class FakeGraphRepository:
    name = "fake"

    def __init__(self) -> None:
        self.authors = {
            "author:an": {"name": "An Nguyen", "identity_status": "verified"},
            "author:binh": {"name": "Binh Tran", "identity_status": "verified"},
            "author:linh-a": {"name": "Linh Nguyen", "identity_status": "verified"},
            "author:linh-b": {"name": "Linh Nguyen", "identity_status": "source_only"},
        }
        self.papers = {
            "paper:rag": {
                "title": "Graph Evidence for NLP",
                "year": 2024,
                "url": "https://example.org/papers/rag",
            },
            "paper:safety": {
                "title": "Safe Language Models",
                "year": 2025,
                "url": "https://example.org/papers/safety",
            },
            "paper:mt": {
                "title": "Neural Translation Paths",
                "year": 2023,
                "url": "https://example.org/papers/mt",
            },
            "paper:solo": {
                "title": "Solo Parsing Study",
                "year": 2025,
                "url": "https://example.org/papers/solo",
            },
        }
        self.institutions = {
            "inst:hust": "Hanoi University of Science and Technology",
            "inst:vnu": "Vietnam National University",
        }
        self.venues = {"venue:acl": "ACL", "venue:emnlp": "EMNLP"}
        self.topics = {
            "topic:retrieval": "Retrieval and RAG",
            "topic:safety_eval": "Safety and LLM evaluation",
        }
        self.methods = {
            "method:graphrag": "GraphRAG",
            "method:qwen": "Qwen",
        }
        self.datasets = {
            "dataset:nlpgraph-bench": "NLPGraph Bench",
            "dataset:safetybench": "SafetyBench",
        }
        self.tasks = {
            "task:question-answering": "Question Answering",
            "task:safety-evaluation": "Safety Evaluation",
        }
        self.paper_authors = {
            "paper:rag": ["author:an", "author:binh"],
            "paper:safety": ["author:binh", "author:linh-a"],
            "paper:mt": ["author:an", "author:linh-a"],
            "paper:solo": ["author:linh-b"],
        }
        self.affiliations = {
            ("author:an", "paper:rag"): "inst:hust",
            ("author:binh", "paper:rag"): "inst:vnu",
            ("author:binh", "paper:safety"): "inst:hust",
            ("author:linh-a", "paper:safety"): "inst:hust",
            ("author:linh-a", "paper:mt"): "inst:vnu",
        }
        self.paper_topics = {"paper:rag": "topic:retrieval", "paper:safety": "topic:safety_eval"}
        self.paper_venues = {
            "paper:rag": "venue:acl",
            "paper:safety": "venue:emnlp",
            "paper:mt": "venue:acl",
            "paper:solo": "venue:emnlp",
        }
        self.citations = {("paper:safety", "paper:rag")}
        self.paper_methods = {
            "paper:rag": ["method:graphrag"],
            "paper:safety": ["method:qwen"],
        }
        self.paper_datasets = {
            "paper:rag": ["dataset:nlpgraph-bench"],
            "paper:safety": ["dataset:safetybench"],
        }
        self.paper_tasks = {
            "paper:rag": ["task:question-answering"],
            "paper:safety": ["task:safety-evaluation"],
        }

    async def entity_catalog(self, *, force_refresh: bool = False) -> list[EntityRecord]:
        _ = force_refresh
        records: list[EntityRecord] = []
        for entity_id, data in self.authors.items():
            records.append(EntityRecord(entity_id, "Author", data["name"], data["identity_status"]))
        for entity_id, data in self.papers.items():
            records.append(EntityRecord(entity_id, "Paper", data["title"]))
        for entity_id, name in self.institutions.items():
            records.append(EntityRecord(entity_id, "Institution", name))
        for entity_id, name in self.venues.items():
            records.append(EntityRecord(entity_id, "Venue", name))
        for entity_id, name in self.topics.items():
            records.append(EntityRecord(entity_id, "Topic", name))
        for entity_id, name in self.methods.items():
            records.append(EntityRecord(entity_id, "Method", name))
        for entity_id, name in self.datasets.items():
            records.append(EntityRecord(entity_id, "Dataset", name))
        for entity_id, name in self.tasks.items():
            records.append(EntityRecord(entity_id, "Task", name))
        return records

    async def execute(self, step: QueryStep) -> GraphQueryResult:
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
            QueryAction.PAPER_METHODS: self._paper_methods,
            QueryAction.METHOD_PAPERS: self._method_papers,
            QueryAction.PAPER_DATASETS: self._paper_datasets,
            QueryAction.DATASET_PAPERS: self._dataset_papers,
            QueryAction.PAPER_TASKS: self._paper_tasks,
            QueryAction.TASK_PAPERS: self._task_papers,
            QueryAction.METHOD_TRENDS: self._method_trends,
        }
        records = handlers[step.action](step.params)
        limit = min(step.limit, 100)
        return GraphQueryResult(records=records[:limit], truncated=len(records) > limit)

    async def health(self) -> tuple[bool, str]:
        return True, "synthetic graph ready"

    async def preview(self) -> dict[str, Any]:
        return {
            "watermark": "SIMULATED — no real LLM/DB",
            "nodes": {
                "Author": len(self.authors),
                "Paper": len(self.papers),
                "Institution": len(self.institutions),
                "Venue": len(self.venues),
                "Topic": len(self.topics),
                "Method": len(self.methods),
                "Dataset": len(self.datasets),
                "Task": len(self.tasks),
            },
            "relationship_types": [action.value for action in QueryAction],
        }

    async def close(self) -> None:
        return None

    def _source(self, paper_id: str) -> dict[str, str]:
        paper = self.papers[paper_id]
        return {"paper_id": paper_id, "title": paper["title"], "url": paper["url"]}

    def _record(
        self,
        subject_id: str,
        predicate: str,
        object_id: str | None,
        value: Any,
        paper_ids: list[str],
        *,
        year: int | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        source_url = self.papers[paper_ids[0]]["url"] if len(paper_ids) == 1 else None
        return {
            "subject_id": subject_id,
            "predicate": predicate,
            "object_id": object_id,
            "value": value,
            "paper_ids": paper_ids,
            "source_url": source_url,
            "year": year,
            "title": title,
        }

    def _papers_for_author(self, author_id: str) -> list[str]:
        return [paper_id for paper_id, authors in self.paper_authors.items() if author_id in authors]

    def _author_papers(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        for paper_id in self._papers_for_author(params["author_id"]):
            paper = self.papers[paper_id]
            if params.get("year_from") and paper["year"] < params["year_from"]:
                continue
            if params.get("year_to") and paper["year"] > params["year_to"]:
                continue
            position = self.paper_authors[paper_id].index(params["author_id"]) + 1
            value = {
                "name": paper["title"],
                "title": paper["title"],
                "position": position,
                "sources": [self._source(paper_id)],
            }
            rows.append(
                self._record(
                    params["author_id"],
                    "AUTHORED",
                    paper_id,
                    value,
                    [paper_id],
                    year=paper["year"],
                    title=paper["title"],
                )
            )
        return sorted(rows, key=lambda row: row["year"], reverse=True)

    def _coauthors(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        author_id = params["author_id"]
        evidence: dict[str, list[str]] = {}
        for paper_id in self._papers_for_author(author_id):
            for other_id in self.paper_authors[paper_id]:
                if other_id != author_id:
                    evidence.setdefault(other_id, []).append(paper_id)
        rows = []
        for other_id, paper_ids in evidence.items():
            sources = [self._source(paper_id) for paper_id in paper_ids]
            value = {
                "name": self.authors[other_id]["name"],
                "shared_count": len(paper_ids),
                "sources": sources,
            }
            rows.append(self._record(author_id, "COAUTHORED_WITH", other_id, value, paper_ids))
        return sorted(rows, key=lambda row: (-row["value"]["shared_count"], row["value"]["name"]))

    def _shared_papers(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        for paper_id, authors in self.paper_authors.items():
            if params["author_id"] not in authors or params["other_author_id"] not in authors:
                continue
            paper = self.papers[paper_id]
            value = {"name": paper["title"], "title": paper["title"], "sources": [self._source(paper_id)]}
            rows.append(
                self._record(
                    params["author_id"],
                    "SHARED_PAPER_WITH",
                    params["other_author_id"],
                    value,
                    [paper_id],
                    year=paper["year"],
                    title=paper["title"],
                )
            )
        return rows

    def _author_affiliations(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        for (author_id, paper_id), institution_id in self.affiliations.items():
            if author_id != params["author_id"]:
                continue
            paper = self.papers[paper_id]
            value = {
                "name": self.institutions[institution_id],
                "paper_title": paper["title"],
                "sources": [self._source(paper_id)],
            }
            rows.append(
                self._record(
                    author_id,
                    "AFFILIATED_WITH_ON_PAPER",
                    institution_id,
                    value,
                    [paper_id],
                    year=paper["year"],
                    title=paper["title"],
                )
            )
        return rows

    def _coauthor_affiliations(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        author_id = params["author_id"]
        for paper_id in self._papers_for_author(author_id):
            for coauthor_id in self.paper_authors[paper_id]:
                if coauthor_id == author_id:
                    continue
                institution_id = self.affiliations.get((coauthor_id, paper_id))
                if institution_id is None:
                    continue
                paper = self.papers[paper_id]
                value = {
                    "name": self.institutions[institution_id],
                    "coauthor_id": coauthor_id,
                    "coauthor_name": self.authors[coauthor_id]["name"],
                    "paper_title": paper["title"],
                    "sources": [self._source(paper_id)],
                }
                rows.append(
                    self._record(
                        author_id,
                        "COAUTHOR_AFFILIATION_ON_SHARED_PAPER",
                        institution_id,
                        value,
                        [paper_id],
                        year=paper["year"],
                        title=paper["title"],
                    )
                )
        return rows

    def _paper_authors(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        paper_id = params["paper_id"]
        paper = self.papers[paper_id]
        rows = []
        for index, author_id in enumerate(self.paper_authors[paper_id], start=1):
            predicate = "FIRST_AUTHOR_OF" if index == 1 else "OTHER_AUTHOR_OF"
            value = {
                "name": self.authors[author_id]["name"],
                "position": index,
                "sources": [self._source(paper_id)],
            }
            rows.append(
                self._record(
                    paper_id,
                    predicate,
                    author_id,
                    value,
                    [paper_id],
                    year=paper["year"],
                    title=paper["title"],
                )
            )
        return rows

    def _topic_papers(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        for paper_id, topic_id in self.paper_topics.items():
            if topic_id != params["topic_id"]:
                continue
            paper = self.papers[paper_id]
            if params.get("year_from") and paper["year"] < params["year_from"]:
                continue
            if params.get("year_to") and paper["year"] > params["year_to"]:
                continue
            value = {
                "name": paper["title"],
                "title": paper["title"],
                "rule_id": "synthetic",
                "sources": [self._source(paper_id)],
            }
            rows.append(
                self._record(
                    topic_id,
                    "HAS_LABELLED_PAPER",
                    paper_id,
                    value,
                    [paper_id],
                    year=paper["year"],
                    title=paper["title"],
                )
            )
        return rows

    def _paper_venue(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        paper_id = params["paper_id"]
        venue_id = self.paper_venues[paper_id]
        paper = self.papers[paper_id]
        value = {"name": self.venues[venue_id], "kind": "conference", "sources": [self._source(paper_id)]}
        return [
            self._record(
                paper_id, "APPEARS_IN", venue_id, value, [paper_id], year=paper["year"], title=paper["title"]
            )
        ]

    def _paper_citations(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        direction = params.get("direction", "both")
        for citing_id, cited_id in self.citations:
            if params["paper_id"] == citing_id and direction in {"outgoing", "both"}:
                other_id, predicate = cited_id, "CITES_IN_CORPUS"
            elif params["paper_id"] == cited_id and direction in {"incoming", "both"}:
                other_id, predicate = citing_id, "CITED_BY_IN_CORPUS"
            else:
                continue
            paper = self.papers[other_id]
            value = {"name": paper["title"], "title": paper["title"], "sources": [self._source(other_id)]}
            rows.append(
                self._record(
                    params["paper_id"],
                    predicate,
                    other_id,
                    value,
                    [other_id],
                    year=paper["year"],
                    title=paper["title"],
                )
            )
        return rows

    def _org_collaborations(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        institution_id = params["institution_id"]
        evidence: dict[str, list[str]] = {}
        for paper_id, authors in self.paper_authors.items():
            institutions = {
                self.affiliations[(author_id, paper_id)]
                for author_id in authors
                if (author_id, paper_id) in self.affiliations
            }
            if institution_id not in institutions:
                continue
            for other_id in institutions:
                if other_id != institution_id:
                    evidence.setdefault(other_id, []).append(paper_id)
        rows = []
        for other_id, paper_ids in evidence.items():
            value = {
                "name": self.institutions[other_id],
                "shared_count": len(paper_ids),
                "sources": [self._source(paper_id) for paper_id in paper_ids],
            }
            rows.append(self._record(institution_id, "ORG_COAUTHORED_WITH", other_id, value, paper_ids))
        return rows

    def _author_path(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        start = params["author_id"]
        target = params["other_author_id"]
        queue: list[tuple[str, list[str], list[str]]] = [(start, [start], [])]
        visited = {start}
        while queue:
            current, author_path, paper_path = queue.pop(0)
            if current == target:
                value = {
                    "name": self.authors[target]["name"],
                    "author_ids": author_path,
                    "author_names": [self.authors[author_id]["name"] for author_id in author_path],
                    "hop_count": len(author_path) - 1,
                    "sources": [self._source(paper_id) for paper_id in paper_path],
                }
                return [self._record(start, "COAUTHOR_PATH", target, value, paper_path)]
            if len(author_path) > 4:
                continue
            for row in self._coauthors({"author_id": current}):
                neighbor = row["object_id"]
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                queue.append((neighbor, [*author_path, neighbor], [*paper_path, row["paper_ids"][0]]))
        return []

    def _network_top(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        _ = params
        rows = []
        for author_id, data in self.authors.items():
            coauthors = self._coauthors({"author_id": author_id})
            value = {
                "name": data["name"],
                "metric": "distinct_coauthor_count",
                "metric_value": len(coauthors),
                "shared_paper_edge_sum": sum(row["value"]["shared_count"] for row in coauthors),
                "sources": [],
            }
            rows.append(self._record("network", "RANKED_BY_COAUTHOR_COUNT", author_id, value, []))
        return sorted(rows, key=lambda row: (-row["value"]["metric_value"], row["value"]["name"]))

    def _paper_assets(
        self,
        paper_id: str,
        mapping: dict[str, list[str]],
        names: dict[str, str],
        predicate: str,
    ) -> list[dict[str, Any]]:
        paper = self.papers[paper_id]
        rows = []
        for asset_id in mapping.get(paper_id, []):
            value = {
                "name": names[asset_id],
                "source_kind": "synthetic",
                "confidence_band": "fixture",
                "evidence_texts": [f"Synthetic evidence for {names[asset_id]}."],
                "sources": [self._source(paper_id)],
            }
            rows.append(
                self._record(
                    paper_id,
                    predicate,
                    asset_id,
                    value,
                    [paper_id],
                    year=paper["year"],
                    title=paper["title"],
                )
            )
        return rows

    def _asset_papers(
        self,
        asset_id: str,
        mapping: dict[str, list[str]],
        predicate: str,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        rows = []
        for paper_id, asset_ids in mapping.items():
            if asset_id not in asset_ids:
                continue
            paper = self.papers[paper_id]
            if params.get("year_from") and paper["year"] < params["year_from"]:
                continue
            if params.get("year_to") and paper["year"] > params["year_to"]:
                continue
            value = {
                "name": paper["title"],
                "title": paper["title"],
                "source_kind": "synthetic",
                "confidence_band": "fixture",
                "evidence_texts": [f"Synthetic evidence for {paper['title']}."],
                "sources": [self._source(paper_id)],
            }
            rows.append(
                self._record(
                    asset_id,
                    predicate,
                    paper_id,
                    value,
                    [paper_id],
                    year=paper["year"],
                    title=paper["title"],
                )
            )
        return sorted(rows, key=lambda row: (-row["year"], row["title"]))

    def _paper_methods(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        return self._paper_assets(params["paper_id"], self.paper_methods, self.methods, "USES_METHOD")

    def _method_papers(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        return self._asset_papers(params["method_id"], self.paper_methods, "METHOD_USED_BY_PAPER", params)

    def _paper_datasets(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        return self._paper_assets(params["paper_id"], self.paper_datasets, self.datasets, "EVALUATED_ON")

    def _dataset_papers(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        return self._asset_papers(params["dataset_id"], self.paper_datasets, "DATASET_USED_BY_PAPER", params)

    def _paper_tasks(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        return self._paper_assets(params["paper_id"], self.paper_tasks, self.tasks, "ADDRESSES_TASK")

    def _task_papers(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        return self._asset_papers(params["task_id"], self.paper_tasks, "TASK_ADDRESSED_BY_PAPER", params)

    def _method_trends(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        for method_id, method_name in self.methods.items():
            paper_ids = []
            for paper_id, method_ids in self.paper_methods.items():
                paper = self.papers[paper_id]
                if method_id not in method_ids:
                    continue
                if params.get("year_from") and paper["year"] < params["year_from"]:
                    continue
                if params.get("year_to") and paper["year"] > params["year_to"]:
                    continue
                paper_ids.append(paper_id)
            if not paper_ids:
                continue
            value = {
                "name": method_name,
                "metric": "distinct_paper_count",
                "metric_value": len(paper_ids),
                "sources": [self._source(paper_id) for paper_id in paper_ids[:5]],
            }
            rows.append(
                self._record(
                    "method-trends",
                    "RANKED_METHOD_BY_PAPER_COUNT",
                    method_id,
                    value,
                    paper_ids[:5],
                )
            )
        return sorted(rows, key=lambda row: (-row["value"]["metric_value"], row["value"]["name"]))
