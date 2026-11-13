"""Developer-owned, parameterized, read-only Cypher catalog."""

from __future__ import annotations

import re
from dataclasses import dataclass

from graphrag.models import QueryAction


@dataclass(frozen=True)
class CypherTemplate:
    action: QueryAction
    cypher: str
    required_params: frozenset[str]


WRITE_KEYWORDS = re.compile(
    r"\b(CREATE|MERGE|SET|DELETE|DETACH|DROP|REMOVE|FOREACH|LOAD\s+CSV|CALL\s+db\.index)\b",
    re.IGNORECASE,
)


def _template(action: QueryAction, cypher: str, *required: str) -> CypherTemplate:
    normalized = "\n".join(line.rstrip() for line in cypher.strip().splitlines())
    if WRITE_KEYWORDS.search(normalized):
        raise ValueError(f"write operation is forbidden in template {action}")
    return CypherTemplate(action=action, cypher=normalized, required_params=frozenset(required))


TEMPLATES: dict[QueryAction, CypherTemplate] = {
    QueryAction.AUTHOR_PAPERS: _template(
        QueryAction.AUTHOR_PAPERS,
        """
        MATCH (a:Author {id: $author_id})-[r:FIRST_AUTHOR_OF|OTHER_AUTHOR_OF]->(p:Paper)
        WHERE a.scope_id = $scope AND r.scope_id = $scope AND p.scope_id = $scope
          AND ($year_from IS NULL OR p.year >= $year_from)
          AND ($year_to IS NULL OR p.year <= $year_to)
        RETURN a.id AS subject_id, 'AUTHORED' AS predicate, p.id AS object_id,
          {title: p.title, name: p.title, position: r.position,
           sources: [{paper_id: p.id, title: p.title, url: p.source_url}]} AS value,
          [p.id] AS paper_ids, p.source_url AS source_url, p.year AS year, p.title AS title
        ORDER BY p.year DESC, p.title LIMIT $limit
        """,
        "author_id",
    ),
    QueryAction.COAUTHORS: _template(
        QueryAction.COAUTHORS,
        """
        MATCH (a:Author {id: $author_id})-[r:COAUTHORED_WITH]-(b:Author)
        WHERE a.scope_id = $scope AND r.scope_id = $scope AND b.scope_id = $scope
        OPTIONAL MATCH (p:Paper) WHERE p.id IN r.evidence_paper_ids AND p.scope_id = $scope
        WITH a, b, r, collect({paper_id: p.id, title: p.title, url: p.source_url}) AS sources
        RETURN a.id AS subject_id, 'COAUTHORED_WITH' AS predicate, b.id AS object_id,
          {name: b.name, shared_count: r.shared_count, sources: sources} AS value,
          r.evidence_paper_ids AS paper_ids, null AS source_url, r.last_year AS year, null AS title
        ORDER BY r.shared_count DESC, b.name LIMIT $limit
        """,
        "author_id",
    ),
    QueryAction.SHARED_PAPERS: _template(
        QueryAction.SHARED_PAPERS,
        """
        MATCH (a:Author {id: $author_id})-[r:COAUTHORED_WITH]-(b:Author {id: $other_author_id})
        WHERE a.scope_id = $scope AND b.scope_id = $scope AND r.scope_id = $scope
        UNWIND r.evidence_paper_ids AS paper_id
        MATCH (p:Paper {id: paper_id}) WHERE p.scope_id = $scope
        RETURN a.id AS subject_id, 'SHARED_PAPER_WITH' AS predicate, b.id AS object_id,
          {name: p.title, title: p.title,
           sources: [{paper_id: p.id, title: p.title, url: p.source_url}]} AS value,
          [p.id] AS paper_ids, p.source_url AS source_url, p.year AS year, p.title AS title
        ORDER BY p.year DESC, p.title LIMIT $limit
        """,
        "author_id",
        "other_author_id",
    ),
    QueryAction.AUTHOR_AFFILIATIONS: _template(
        QueryAction.AUTHOR_AFFILIATIONS,
        """
        MATCH (a:Author {id: $author_id})-[r:AFFILIATED_WITH]->(i:Institution)
        WHERE a.scope_id = $scope AND r.scope_id = $scope AND i.scope_id = $scope
        UNWIND r.evidence_paper_ids AS paper_id
        MATCH (p:Paper {id: paper_id}) WHERE p.scope_id = $scope
        RETURN a.id AS subject_id, 'AFFILIATED_WITH_ON_PAPER' AS predicate, i.id AS object_id,
          {name: i.name, paper_title: p.title,
           sources: [{paper_id: p.id, title: p.title, url: p.source_url}]} AS value,
          [p.id] AS paper_ids, p.source_url AS source_url, p.year AS year, p.title AS title
        ORDER BY p.year DESC, i.name LIMIT $limit
        """,
        "author_id",
    ),
    QueryAction.COAUTHOR_AFFILIATIONS: _template(
        QueryAction.COAUTHOR_AFFILIATIONS,
        """
        MATCH (a:Author {id: $author_id})-[co:COAUTHORED_WITH]-(b:Author)
        MATCH (b)-[af:AFFILIATED_WITH]->(i:Institution)
        WHERE a.scope_id = $scope AND co.scope_id = $scope AND b.scope_id = $scope
          AND af.scope_id = $scope AND i.scope_id = $scope
        WITH a, b, i, [pid IN co.evidence_paper_ids WHERE pid IN af.evidence_paper_ids] AS shared_ids
        UNWIND shared_ids AS paper_id
        MATCH (p:Paper {id: paper_id}) WHERE p.scope_id = $scope
        RETURN a.id AS subject_id, 'COAUTHOR_AFFILIATION_ON_SHARED_PAPER' AS predicate, i.id AS object_id,
          {name: i.name, coauthor_id: b.id, coauthor_name: b.name, paper_title: p.title,
           sources: [{paper_id: p.id, title: p.title, url: p.source_url}]} AS value,
          [p.id] AS paper_ids, p.source_url AS source_url, p.year AS year, p.title AS title
        ORDER BY p.year DESC, b.name, i.name LIMIT $limit
        """,
        "author_id",
    ),
    QueryAction.PAPER_AUTHORS: _template(
        QueryAction.PAPER_AUTHORS,
        """
        MATCH (a:Author)-[r:FIRST_AUTHOR_OF|OTHER_AUTHOR_OF]->(p:Paper {id: $paper_id})
        WHERE a.scope_id = $scope AND r.scope_id = $scope AND p.scope_id = $scope
        RETURN p.id AS subject_id, type(r) AS predicate, a.id AS object_id,
          {name: a.name, position: r.position,
           sources: [{paper_id: p.id, title: p.title, url: p.source_url}]} AS value,
          [p.id] AS paper_ids, p.source_url AS source_url, p.year AS year, p.title AS title
        ORDER BY r.position ASC LIMIT $limit
        """,
        "paper_id",
    ),
    QueryAction.TOPIC_PAPERS: _template(
        QueryAction.TOPIC_PAPERS,
        """
        MATCH (p:Paper)-[r:HAS_TOPIC]->(t:Topic {id: $topic_id})
        WHERE p.scope_id = $scope AND r.scope_id = $scope AND t.scope_id = $scope
          AND ($year_from IS NULL OR p.year >= $year_from)
          AND ($year_to IS NULL OR p.year <= $year_to)
        RETURN t.id AS subject_id, 'HAS_LABELLED_PAPER' AS predicate, p.id AS object_id,
          {name: p.title, title: p.title, rule_id: r.rule_id,
           sources: [{paper_id: p.id, title: p.title, url: p.source_url}]} AS value,
          [p.id] AS paper_ids, p.source_url AS source_url, p.year AS year, p.title AS title
        ORDER BY p.year DESC, p.title LIMIT $limit
        """,
        "topic_id",
    ),
    QueryAction.PAPER_VENUE: _template(
        QueryAction.PAPER_VENUE,
        """
        MATCH (p:Paper {id: $paper_id})-[r:APPEARS_IN]->(v:Venue)
        WHERE p.scope_id = $scope AND r.scope_id = $scope AND v.scope_id = $scope
        RETURN p.id AS subject_id, 'APPEARS_IN' AS predicate, v.id AS object_id,
          {name: v.name, kind: v.kind,
           sources: [{paper_id: p.id, title: p.title, url: p.source_url}]} AS value,
          [p.id] AS paper_ids, p.source_url AS source_url, p.year AS year, p.title AS title
        LIMIT $limit
        """,
        "paper_id",
    ),
    QueryAction.PAPER_CITATIONS: _template(
        QueryAction.PAPER_CITATIONS,
        """
        MATCH (anchor:Paper {id: $paper_id})
        WHERE anchor.scope_id = $scope
        CALL (anchor) {
          MATCH (anchor)-[r:CITES]->(other:Paper)
          WHERE r.scope_id = $scope AND other.scope_id = $scope AND $direction IN ['outgoing', 'both']
          RETURN r, other, 'CITES_IN_CORPUS' AS relation
          UNION ALL
          MATCH (other:Paper)-[r:CITES]->(anchor)
          WHERE r.scope_id = $scope AND other.scope_id = $scope AND $direction IN ['incoming', 'both']
          RETURN r, other, 'CITED_BY_IN_CORPUS' AS relation
        }
        RETURN anchor.id AS subject_id, relation AS predicate, other.id AS object_id,
          {name: other.title, title: other.title,
           sources: [{paper_id: other.id, title: other.title, url: other.source_url}]} AS value,
          [other.id] AS paper_ids, other.source_url AS source_url, other.year AS year, other.title AS title
        ORDER BY other.year DESC, other.title LIMIT $limit
        """,
        "paper_id",
        "direction",
    ),
    QueryAction.ORG_COLLABORATIONS: _template(
        QueryAction.ORG_COLLABORATIONS,
        """
        MATCH (i:Institution {id: $institution_id})-[r:ORG_COAUTHORED_WITH]-(j:Institution)
        WHERE i.scope_id = $scope AND r.scope_id = $scope AND j.scope_id = $scope
        OPTIONAL MATCH (p:Paper) WHERE p.id IN r.evidence_paper_ids AND p.scope_id = $scope
        WITH i, j, r, collect({paper_id: p.id, title: p.title, url: p.source_url}) AS sources
        RETURN i.id AS subject_id, 'ORG_COAUTHORED_WITH' AS predicate, j.id AS object_id,
          {name: j.name, shared_count: r.shared_count, sources: sources} AS value,
          r.evidence_paper_ids AS paper_ids, null AS source_url, r.last_year AS year, null AS title
        ORDER BY r.shared_count DESC, j.name LIMIT $limit
        """,
        "institution_id",
    ),
    QueryAction.AUTHOR_PATH: _template(
        QueryAction.AUTHOR_PATH,
        """
        MATCH (a:Author {id: $author_id}), (b:Author {id: $other_author_id})
        WHERE a.scope_id = $scope AND b.scope_id = $scope
        MATCH path = shortestPath((a)-[:COAUTHORED_WITH*1..4]-(b))
        WHERE all(n IN nodes(path) WHERE n.scope_id = $scope)
          AND all(r IN relationships(path) WHERE r.scope_id = $scope)
        WITH a, b, path,
          [r IN relationships(path) | r.evidence_paper_ids] AS edge_paper_ids
        WITH a, b, path, reduce(all_ids = [], ids IN edge_paper_ids | all_ids + ids) AS paper_ids
        UNWIND paper_ids AS paper_id
        MATCH (p:Paper {id: paper_id}) WHERE p.scope_id = $scope
        WITH a, b, path, collect(DISTINCT {paper_id: p.id, title: p.title, url: p.source_url}) AS sources,
          collect(DISTINCT p.id) AS evidence_ids
        RETURN a.id AS subject_id, 'COAUTHOR_PATH' AS predicate, b.id AS object_id,
          {name: b.name, author_ids: [n IN nodes(path) | n.id],
           author_names: [n IN nodes(path) | n.name], hop_count: length(path), sources: sources} AS value,
          evidence_ids AS paper_ids, null AS source_url, null AS year, null AS title
        LIMIT $limit
        """,
        "author_id",
        "other_author_id",
    ),
    QueryAction.NETWORK_TOP: _template(
        QueryAction.NETWORK_TOP,
        """
        MATCH (a:Author)-[r:COAUTHORED_WITH]-(b:Author)
        WHERE a.scope_id = $scope AND r.scope_id = $scope AND b.scope_id = $scope
        WITH a, count(DISTINCT b) AS coauthor_count, sum(r.shared_count) AS shared_paper_edge_sum
        RETURN 'network' AS subject_id, 'RANKED_BY_COAUTHOR_COUNT' AS predicate, a.id AS object_id,
          {name: a.name, metric: 'distinct_coauthor_count', metric_value: coauthor_count,
           shared_paper_edge_sum: shared_paper_edge_sum, sources: []} AS value,
          [] AS paper_ids, null AS source_url, null AS year, null AS title
        ORDER BY coauthor_count DESC, a.name LIMIT $limit
        """,
    ),
}


def get_template(action: QueryAction) -> CypherTemplate:
    return TEMPLATES[action]
