# Execution log (nlpgraph-v1)

Host: Windows 11, Python 3.13 (uv 0.11.1), repo D:\nlp-collab-graph. Times are local (UTC+7), 2026-11-03.
No secrets are recorded here.

## Checklist / status

| Phase | Status | Evidence |
|---|---|---|
| Preflight: repo, tooling, API probes | PASSED | ACL XML 200, arXiv API 200, OpenAlex DOI lookup 200 |
| Data contracts + fixtures + tests | PASSED | `uv run pytest -q` 46 passed |
| Fetch ACL / arXiv / OpenAlex | PASSED | 840 ACL + 252 arXiv; OpenAlex 1090/1092 matched (logs/fetch.log) |
| Normalize + topics + export | PASSED | 8 JSONL + manifest, `validate` PASSED |
| Topic pilot (50 papers) | PASSED | evaluation/topic_pilot.json, rules frozen at topics-v1.1 |
| Dry-run import plan | PASSED | output/neo4j/import_plan_dry_run.json: 7,134 nodes, 30,971 rels, 0 rejected |
| AuraDB preflight / import / idempotency | PASSED | output/neo4j/preflight.json, import_report_latest.json, idempotency_check.json |
| Author network analysis | PASSED (local source) | output/analysis/* |
| QA sampling + automated verification | PARTIAL | automated_preliminary only; no human labels |
| Source audits | PASSED | evaluation/source_audits.json |
| Report PDF | PASSED (pending cloud section) | report/final.pdf, rendered pages inspected |

## Commands and results (in order)
1. Probes: `curl` ACL XML (6 collections 200), arXiv `cat:cs.CL` 200, OpenAlex `/works/doi:10.18653/v1/2023.acl-long.1` 200.
2. `uv sync` -> OK (later `uv add scipy numpy` because `networkx.pagerank` needs scipy).
3. `src.cli fetch` run 1 -> FAILED: OpenAlex HTTP 400. Cause: `authors_count` is not a valid `select` field
   (confirmed from the API error body). Fix: removed it from configs/scope.yaml. Run 2 -> PASSED (exit 0).
4. `pytest` -> 1 failure in my own test constant (Wilson 19/20 lower bound is 0.764, not <0.76). Fixed the test to the
   reference value; 46 passed.
5. `prepare` + `validate` -> PASSED. 50-paper topic pilot: 18/18 assigned labels plausible, one false negative
   (speech translation) -> added `mt.speech_translation`, rule_version topics-v1.1, then frozen.
6. QA round 0 (seed 20261107): 200/200 "correct" -> recognised as circular (verifier read the same OpenAlex record
   that created the edge). Kept in evaluation/round0_weak_verifier/, not used for claims.
7. Verifier rewritten to use ACL-printed affiliations as an independent source. QA round 1 (pre-fix, seed 20261107,
   tag `prefix`): micro 0.8786 (CI 0.840-0.917), AFFILIATED_WITH 0.50, ORG_COAUTHORED_WITH 0.45, ACTIVE_IN 0.75.
   Audit: 72.5% of affiliation rows agree with ACL strings.
8. Root cause: OpenAlex assigns institutions the author did not print, and 23 works smear paper-level affiliations
   onto every author. Fix in normalize.py (drop institutions contradicting the ACL-printed affiliation: 754 rows;
   drop smeared rows without ACL string: 115 rows). Re-prepare/validate PASSED.
9. QA round 2 (fresh seed 20261108, tag `postfix`): 165 correct / 0 incorrect / 35 unverifiable;
   micro 0.8895 (CI 0.857-0.922) with unverifiable counted as not correct. Independence caveat recorded in
   evaluation/fix_log.json (post-fix ACL-side affiliation agreement is true by construction).
10. `analyze` -> PASSED (6.8 s): 5,430 authors, 16,754 co-author edges, LCC 970 (17.9%), Louvain 624 communities,
    modularity 0.984; small-world: C_obs 0.913, L_obs 10.99 vs C_rand 0.015, L_rand 3.31, sigma 17.9, verdict
    "no clear small-world indication" (L_obs far above L_rand).
11. `report` -> 11-page PDF; page renders checked (Vietnamese diacritics OK; fixed floor-bracket glyph).

## Blockers
- (resolved 15:47) `.env` created at the user's explicit request from values the user supplied in chat; recommend
  rotating NEO4J_PASSWORD and OPENALEX_API_KEY since they appeared in a conversation.
12. `preflight` -> Neo4j/5.27-aura, RETURN 1 OK, instance empty (0 nodes / 0 rels, no foreign data).
13. `import` -> VERIFIED in ~87 s: 7,134 nodes, 30,971 relationships, 10/10 types, 0 parallel duplicates,
    0 relationships without evidence, 0 orphans; counts equal the plan.
14. `idempotency` -> IDEMPOTENT (7,134 / 30,971 -> 7,134 / 30,971).
15. `queries` -> 5 example Cypher queries with real rows (output/neo4j/example_queries.json).
16. `analyze --source neo4j` -> identical stats to the local projection (LCC 970, 16,754 edges).
17. `report` -> 13-page PDF including the AuraDB section.
- Remaining: human QA labels do not exist; all precision numbers are `automated_preliminary`.
