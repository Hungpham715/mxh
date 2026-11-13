"""Validated contracts shared by parsing, retrieval, generation, and the API."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


class IntentName(StrEnum):
    AUTHOR_PAPERS = "author_papers"
    COAUTHORS = "coauthors"
    SHARED_PAPERS = "shared_papers"
    AUTHOR_AFFILIATIONS = "author_affiliations"
    COAUTHOR_AFFILIATIONS = "coauthor_affiliations"
    PAPER_AUTHORS = "paper_authors"
    TOPIC_PAPERS = "topic_papers"
    PAPER_VENUE = "paper_venue"
    PAPER_CITATIONS = "paper_citations"
    ORG_COLLABORATIONS = "org_collaborations"
    AUTHOR_PATH = "author_path"
    NETWORK_TOP = "network_top"
    UNKNOWN = "unknown"


class QueryAction(StrEnum):
    AUTHOR_PAPERS = "author_papers"
    COAUTHORS = "coauthors"
    SHARED_PAPERS = "shared_papers"
    AUTHOR_AFFILIATIONS = "author_affiliations"
    COAUTHOR_AFFILIATIONS = "coauthor_affiliations"
    PAPER_AUTHORS = "paper_authors"
    TOPIC_PAPERS = "topic_papers"
    PAPER_VENUE = "paper_venue"
    PAPER_CITATIONS = "paper_citations"
    ORG_COLLABORATIONS = "org_collaborations"
    AUTHOR_PATH = "author_path"
    NETWORK_TOP = "network_top"


class EntityMention(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=300)
    type: Literal["Author", "Paper", "Institution", "Venue", "Topic", "Unknown"] = "Unknown"


class QueryFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    year_from: int | None = Field(default=None, ge=1900, le=2100)
    year_to: int | None = Field(default=None, ge=1900, le=2100)
    topic_id: str | None = None
    citation_direction: Literal["outgoing", "incoming", "both"] = "both"

    @model_validator(mode="after")
    def validate_years(self) -> QueryFilters:
        if self.year_from and self.year_to and self.year_from > self.year_to:
            raise ValueError("year_from cannot be greater than year_to")
        return self


class QueryIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: IntentName
    entities: list[EntityMention] = Field(default_factory=list, max_length=5)
    filters: QueryFilters = Field(default_factory=QueryFilters)
    requested_fields: list[str] = Field(default_factory=list, max_length=20)
    unsupported: bool = False
    parse_source: Literal["llm", "rules_fallback", "direct_fixture"] = "llm"


class CandidateEntity(BaseModel):
    id: str
    label: Literal["Author", "Paper", "Institution", "Venue", "Topic"]
    name: str
    score: float = Field(ge=0, le=100)


class LinkedEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Literal["Author", "Paper", "Institution", "Venue", "Topic"]
    id: str
    name: str
    score: float = Field(ge=0, le=100)
    identity_status: str | None = None
    ambiguous_candidates: list[CandidateEntity] = Field(default_factory=list, max_length=3)

    @property
    def is_ambiguous(self) -> bool:
        return bool(self.ambiguous_candidates)


class QueryStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: QueryAction
    params: dict[str, Any]
    expected_fields: list[str]
    limit: int = Field(default=20, ge=1, le=100)
    fingerprint: str = ""

    @model_validator(mode="after")
    def build_fingerprint(self) -> QueryStep:
        canonical = json.dumps(self.params, sort_keys=True, ensure_ascii=False, default=str)
        digest = hashlib.sha256(f"{self.action}:{canonical}".encode()).hexdigest()[:16]
        self.fingerprint = digest
        return self


class GraphFact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fact_id: str
    subject_id: str
    predicate: str
    object_id: str | None = None
    value: Any | None = None
    paper_ids: list[str] = Field(default_factory=list)
    source_url: str | None = None
    year: int | None = None
    claim_type: str
    limitations: list[str] = Field(default_factory=list)
    title: str | None = None

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = HttpUrl(value)
        return str(parsed)


class Citation(BaseModel):
    paper_id: str
    title: str
    url: str
    claim_ids: list[str] = Field(default_factory=list)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return str(HttpUrl(value))


class TraceStep(BaseModel):
    iteration: int = Field(ge=0, le=5)
    action: str
    records: int = Field(default=0, ge=0)
    new_facts: int = Field(default=0, ge=0)
    duration_ms: int = Field(default=0, ge=0)
    status: Literal["ok", "empty", "error", "infrastructure"] = "ok"
    detail: str | None = None


class QueryState(BaseModel):
    question: str
    linked_entities: list[LinkedEntity] = Field(default_factory=list)
    planned_steps: list[QueryStep] = Field(default_factory=list)
    executed: list[QueryStep] = Field(default_factory=list)
    seen_fingerprints: set[str] = Field(default_factory=set)
    facts: list[GraphFact] = Field(default_factory=list)
    goals_remaining: list[str] = Field(default_factory=list)
    iteration: int = Field(default=0, ge=0, le=5)
    max_iterations: int = Field(default=5, ge=1, le=5)
    stop_reason: str | None = None
    status: Literal["running", "answered", "partial", "not_found", "ambiguous", "out_of_scope", "error"] = (
        "running"
    )
    sources: list[Citation] = Field(default_factory=list)
    answer: str = ""
    trace: list[TraceStep] = Field(default_factory=list)
    llm_calls: int = Field(default=0, ge=0)


class NextDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sufficient: bool
    missing_goals: list[str] = Field(default_factory=list)
    next_action: QueryAction | None = None
    params: dict[str, Any] | None = None
    reason_code: Literal["enough", "continue", "no_progress", "missing_entity", "limit_reached"]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, max_length=100)
    history: list[dict[str, str]] = Field(default_factory=list, max_length=12)
    debug: bool = False


class ChatResponse(BaseModel):
    answer: str
    status: Literal["answered", "partial", "not_found", "ambiguous", "out_of_scope", "error"]
    complete: bool
    iterations_used: int = Field(ge=0, le=5)
    stop_reason: str
    sources: list[Citation] = Field(default_factory=list)
    facts_count: int = Field(ge=0)
    trace: list[TraceStep] | None = None
    provider_info: dict[str, str] | None = None
    ambiguous_candidates: list[CandidateEntity] = Field(default_factory=list)
    watermark: str | None = None
