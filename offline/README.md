# NLP/LLM research collaboration graph (nlpgraph-v1)

Reproducible pipeline: ACL Anthology + arXiv cs.CL metadata, OpenAlex DOI enrichment, rule-based topics,
8-file JSONL contract, Neo4j AuraDB graph (5 labels, 10 relationship types), author co-authorship network analysis,
evidence-based QA, Vietnamese PDF report. Specification: `architecture.md` (+ `prompt.md`).

```
ACL XML + arXiv API --> data/raw (cached) --> OpenAlex /works/doi:<DOI> --> normalize (IDs, dedup, identity)
   --> topics (rules) --> data/processed/*.jsonl + manifest.json (sha256) --> validate
   --> derive 10 edge types (src/graph/derive.py) --> Neo4j AuraDB (MERGE, scope_id) --> analysis / QA / report
```

## Prerequisites
- Python 3.13 via `uv` (`uv sync`), Windows fonts (Arial) for the PDF.
- `.env` (copy `.env.example`, never commit): `NEO4J_URI` (neo4j+s://), `NEO4J_USERNAME` (`NEO4J_USER` accepted),
  `NEO4J_PASSWORD`, `NEO4J_DATABASE`, optional `OPENALEX_API_KEY`, `OPENALEX_BASE_URL`, `CONTACT_EMAIL`.

## CLI
```bash
uv sync
uv run pytest -q
uv run python -m src.cli fetch --config configs/scope.yaml       # cached, resumable
uv run python -m src.cli prepare --config configs/topics.yaml
uv run python -m src.cli validate --data data/processed
uv run python -m src.cli import --data data/processed --dry-run   # no writes; plan + storage estimate
uv run python -m src.cli preflight                                # read-only Aura check
uv run python -m src.cli import --data data/processed
uv run python -m src.cli idempotency --data data/processed        # re-import, compare counts
uv run python -m src.cli queries                                  # example Cypher with real results
uv run python -m src.cli analyze --out output/analysis [--source neo4j]
uv run python -m src.cli sample --per-type 20 --seed 20261107 [--tag prefix]
uv run python -m src.cli score --labels evaluation/labels.csv [--tag prefix]
uv run python -m src.cli report --out report/final.pdf
bash scripts/run_all.sh                                           # everything, with checkpoints
```
Exit codes: 0 ok, 1 error, 2 invalid snapshot, 3 Neo4j ownership conflict (nothing written), 4 count mismatch,
5 idempotency failure.

## Data contract (schema_version 1)
`papers, authors, institutions, venues, paper_authors, affiliations, citations, paper_topics` (.jsonl) + `manifest.json`.
Details: `docs/schema.md`. Sources and selection: `docs/sources.md`, `configs/scope.yaml`.

## Cloud safety
Only `MERGE` on stable ids; every node/relationship gets `scope_id = nlpgraph-v1`; before writing, the importer refuses
if any of our ids exists without our scope_id; no DELETE/DROP anywhere in the code; batches of 300 with retry.

## Outputs
- `data/processed/` real snapshot (+ `data/rejected/unresolved.csv`, `large_author_papers.jsonl`, `edges.jsonl`)
- `output/analysis/` graph counts, author network JSON/CSV, PNG figures; `output/neo4j/` import reports
- `evaluation/` samples, automated labels (`automated_preliminary`, NOT human), scores, audits, fix log,
  `manual_review_template.csv`
- `report/final.pdf` (+ `final.md`, `sections/`), `execution_log.md`

## Known limitations
Sampled corpus (1,091 papers) so the author network is fragmented; citations are only in-corpus (26);
61% of papers have no topic (precision-first rules); affiliation edges that rely on OpenAlex only cannot be
verified automatically; precision is an automated preliminary estimate pending human review.
