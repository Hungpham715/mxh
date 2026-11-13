"""Dataset contracts used from candidate generation through SFT export."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ReviewStatus(StrEnum):
    UNKNOWN = "unknown"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class EntityMention(BaseModel):
    """A surface entity mention the parser should extract from the question.

    `type` mirrors the runtime ``graphrag.models.EntityMention`` label set but is kept a
    plain string here so the dataset layer stays decoupled from the application package.
    """

    model_config = ConfigDict(extra="forbid")
    text: str
    type: str = "Unknown"


class ExpectedQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: str
    entity_ids: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)


class ExpectedFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    predicates: list[str] = Field(default_factory=list)
    object_ids: list[str] = Field(default_factory=list)
    answer: str = ""


class ExpectedCitations(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paper_ids: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)


class QuestionCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str
    question: str
    language: Literal["vi", "en"] = "vi"
    expected_status: Literal["answered", "partial", "not_found", "ambiguous", "out_of_scope", "error"] = (
        "answered"
    )
    expected_query: ExpectedQuery
    expected_facts: ExpectedFacts = Field(default_factory=ExpectedFacts)
    expected_citations: ExpectedCitations = Field(default_factory=ExpectedCitations)
    # Runtime-aligned fields used to build SFT samples that match the live prompts.
    # `entity_mentions` is the gold PARSE entity list; `filters` the gold PARSE filters;
    # `verified_facts` are the normalized GraphFact dicts the ANSWER prompt will carry.
    entity_mentions: list[EntityMention] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    verified_facts: list[dict[str, Any]] = Field(default_factory=list)
    scope_id: str
    snapshot_version: str
    template_id: str
    group_id: str
    seed: int
    review_status: ReviewStatus = ReviewStatus.UNKNOWN
    reviewer_note: str = ""
    split: Literal["train", "val", "test"] | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


class SFTSample(BaseModel):
    """A chat-format training example.

    `messages` holds the full system/user/assistant turn list so the trainer can apply the
    model's chat template and mask everything but the assistant turn (assistant-only loss).
    This mirrors exactly what the runtime providers feed the model at inference time.
    """

    model_config = ConfigDict(extra="forbid")
    sample_id: str
    task: Literal["PARSE", "ANSWER"]
    messages: list[dict[str, str]]
    split: Literal["train", "val"]
    source_case_id: str


def write_json_schema(path) -> None:
    import json

    path.write_text(
        json.dumps(QuestionCase.model_json_schema(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
