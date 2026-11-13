import re

from graphrag.cypher_templates import TEMPLATES, WRITE_KEYWORDS
from graphrag.models import QueryAction


def test_all_twelve_actions_have_read_only_templates() -> None:
    assert set(TEMPLATES) == set(QueryAction)
    for template in TEMPLATES.values():
        assert not WRITE_KEYWORDS.search(template.cypher)
        assert "$scope" in template.cypher
        assert "$limit" in template.cypher
        assert "scope_id = $scope" in template.cypher


def test_templates_use_parameters_not_user_interpolation() -> None:
    for template in TEMPLATES.values():
        assert "%s" not in template.cypher
        assert "{}" not in template.cypher
        assert not re.search(r"\+\s*\$", template.cypher)
        for parameter in template.required_params:
            assert f"${parameter}" in template.cypher


def test_symmetric_and_path_semantics_are_bounded() -> None:
    assert "[r:COAUTHORED_WITH]-(b:Author)" in TEMPLATES[QueryAction.COAUTHORS].cypher
    path_query = TEMPLATES[QueryAction.AUTHOR_PATH].cypher
    assert "COAUTHORED_WITH*1..4" in path_query
    assert "all(r IN relationships(path) WHERE r.scope_id = $scope)" in path_query


def test_affiliation_query_intersects_evidence_papers() -> None:
    query = TEMPLATES[QueryAction.COAUTHOR_AFFILIATIONS].cypher
    assert "pid IN co.evidence_paper_ids" in query
    assert "pid IN af.evidence_paper_ids" in query
