import pytest
from pydantic import ValidationError

from graphrag.models import GraphFact, QueryAction, QueryStep
from graphrag.settings import Settings


def test_fake_profile_rejects_mixed_providers() -> None:
    with pytest.raises(ValidationError):
        Settings(app_mode="fake", graph_provider="neo4j", llm_provider="fake")


def test_real_profile_never_accepts_fake_llm() -> None:
    with pytest.raises(ValidationError):
        Settings(
            app_mode="real",
            graph_provider="neo4j",
            llm_provider="fake",
            neo4j_uri="neo4j+s://example.databases.neo4j.io",
            neo4j_username="reader",
            neo4j_password="secret",
        )


def test_query_step_fingerprint_is_canonical() -> None:
    first = QueryStep(action=QueryAction.AUTHOR_PAPERS, params={"b": 2, "a": 1}, expected_fields=[])
    second = QueryStep(action=QueryAction.AUTHOR_PAPERS, params={"a": 1, "b": 2}, expected_fields=[])
    assert first.fingerprint == second.fingerprint


def test_invalid_source_url_is_rejected() -> None:
    with pytest.raises(ValidationError):
        GraphFact(
            fact_id="fact",
            subject_id="author:an",
            predicate="AUTHORED",
            paper_ids=["paper:rag"],
            source_url="javascript:alert(1)",
            claim_type="graph_fact",
        )
