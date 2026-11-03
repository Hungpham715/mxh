# Schema (contract v1 + Neo4j)

## JSONL files (UTF-8, one JSON object per line, `null` = unknown)
| File | Fields | Key / rules |
|---|---|---|
| papers.jsonl | id,title,year,abstract,doi,acl_id,arxiv_id,source_kind,source_url,venue_id,openalex_id (+abstract_origin, alias_source_urls) | id `oa:W…` / `acl:` / `arxiv:`; year 2023–2025; DOI/OpenAlex/ACL/arXiv aliases unique |
| authors.jsonl | id,name,orcid,openalex_id,acl_author_id,identity_status | `oa:A…` (verified) or `src:<paper>#<pos>` (source_only/unresolved, single paper) |
| institutions.jsonl | id,name,ror,country_code,source_url | OpenAlex `oa:I…` only |
| venues.jsonl | id,name,kind,year,source_url | kind conference / preprint_server |
| paper_authors.jsonl | paper_id,author_id,position,author_position,source_url | (paper,author); positions 1..n |
| affiliations.jsonl | paper_id,author_id,institution_id,year,raw_affiliation,source_url (+affiliation_check) | must be an authorship of that paper |
| citations.jsonl | citing_paper_id,cited_paper_id,source_url | both in corpus, no self-cite |
| paper_topics.jsonl | paper_id,topic_id,rule_id,evidence_span,confidence_band | ≤2 per paper, span occurs in title/abstract |
| manifest.json | schema_version,scope_id,created_at_utc,source_versions,input_counts,output_counts,unmatched_openalex_count,checksums | written last; sha256 per file |

## Neo4j
Labels: Author, Paper, Institution, Venue, Topic (unique `id` constraint each). Relationship types (whitelist):
FIRST_AUTHOR_OF, OTHER_AUTHOR_OF, COAUTHORED_WITH, AFFILIATED_WITH, APPEARS_IN, HAS_TOPIC, CITES,
ORG_COAUTHORED_WITH, RESEARCHES, ACTIVE_IN. Undirected pairs are stored once as (min_id)->(max_id).
Relationship properties: source_kind, source_url, evidence_paper_ids, evidence_count, first_year, last_year, years,
build_version, scope_id (+ position/author_position, shared_count, rule_id/evidence_span/confidence_band).
Derivation rules: `src/graph/derive.py`; >20-author papers do not generate co-author cliques.
