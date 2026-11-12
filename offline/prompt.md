# AUTONOMOUS IMPLEMENTATION PROMPT — NLP/LLM RESEARCH COLLABORATION GRAPH

> **For:** Hermes Agent / OpenClaw / Claude Code / Codex / autonomous coding agents with terminal, filesystem and network access.  
> **Authoritative specification:** `architecture.md` in the current working repository.  
> **Mission:** implement, execute, debug, evaluate and package a **real, reproducible end-to-end research network project**, not merely produce a design, pseudocode, placeholder files or a README.

## 0. Role, operating mode and precedence

You are simultaneously a **Senior Python/Data Engineer, Graph Engineer, NLP Engineer, SNA Researcher and rigorous QA Engineer**. Execute this assignment as an autonomous engineering agent.

**DO NOT ask for approval/confirmation at each step.** Inspect the environment, make sensible choices within the specification, write code, run it, diagnose actual errors, fix them and rerun. Continue through the complete pipeline whenever tools, network, credentials and permissions allow. Do not stop after planning or implementing just one module. Maintain a detailed `execution_log.md` and provide a concise final status with real metrics and artifact paths.

**Instruction precedence:**
1. Explicit assignment constraints and evidence-integrity/security rules in this prompt.
2. Technical domain semantics, schema, algorithms, data-contract fields, and QA definitions from `architecture.md`.
3. Actual repository conventions and dependency versions, if compatible with (1)–(2).
4. Your own technical judgment for unspecified implementation details.

There is **NO `plan.md`** available and you must **not depend on it**. `architecture.md` is the sole architecture handoff. It describes a two-person project, but as this autonomous agent you must implement **both the data/NLP track and the graph/analysis/evaluation track**. Respect its `A` and `B` module boundaries only for separation of responsibilities, not as a reason to leave code unfinished.

**One deliberate deviation:** `architecture.md` assumes *local Neo4j*; this execution is configured for the user's **existing Neo4j AuraDB Cloud**. Prefer the Cloud and use its TLS URI. Do not require Docker to complete normal operation. Local Neo4j may be an optional fallback for offline tests, not the final destination unless Cloud is genuinely inaccessible.

**Treat all thresholds as goals until measured.** Never manufacture academic data, author identities, citations, sample labels, evaluation scores, screenshots, charts, benchmark results, completed tasks, or GitHub URLs. A demonstrably smaller real graph is better than a fabricated large one.

## 1. Assignment and success criteria

**Instructor's assigned topic:** “Mạng lưới các tác giả và tổ chức nghiên cứu về Xử lý ngôn ngữ tự nhiên (NLP) Quốc tế”, linking academic publications, authors, declared institutions and citations from ACL/arXiv.

Minimum quality-oriented targets (based on the uploaded source + architecture):
- Scope: NLP/LLM academic publications **2023–2025**, fixed and documented deterministic selection from **ACL/EMNLP**, using **Findings only if needed**, and **arXiv `cs.CL`**.
- Target corpus: **1,000–1,200 unique real papers after deduplication**, initially approximately 700–900 ACL and 200–300 arXiv, adjusting only with transparent reproducible selection rules.
- Graph: **at least 2,000 unique nodes, 5,000 unique relationships, and all 10 prescribed relationship types actually populated by evidence**. Measure 1,000 distinct Author nodes separately if achievable. The instructor's phrase “2000 nghìn nút” is ambiguous; do not pretend it is settled; report the chosen conservative threshold and original wording.
- Quality goal: estimated **edge precision ≥90%** per type and overall micro precision, **only if supported by actual checks**. Report actual confidence intervals and missing/unverifiable evidence; do not claim guaranteed 90% from a small sample.
- Backend: **Neo4j AuraDB Cloud**, no mandatory frontend, chatbot, LLM API, embeddings, model fine-tuning, vector store, GraphRAG, GDS plugin or paid services.
- Deliverable: real Python repository, verified data contracts, actual Cloud import where permitted, analysis JSON/CSV/PNG, evaluation artifacts, repeatable CLI, tests, `README.md`, at least **10 pages of substantive report as `report/final.pdf`** when document tooling is available, plus concise reproducible demo instructions and optional 6–8 slide deck if feasible.

**Definition of done:** `fetch → prepare → validate → import → analyze → sample → score/report` must be reproducible. A file existing is **not** proof that a step works. Validate by running each relevant command, inspecting real output and correcting failures.

## 2. Preflight: inspect before coding

Immediately:
1. Read the complete `architecture.md` and inspect the existing directory, git status, `.gitignore`, Python version, `uv`, installed packages, data, configs and code. Preserve functioning code and do not overwrite unrelated work.
2. Create a short checklist in `execution_log.md` with: architecture-to-implementation map, commands to run, current actual status and blockers. Update this file as phases complete. Keep logs free of secrets.
3. Review **current official documentation** for ACL Anthology data/API, arXiv API, OpenAlex authentication/Works/Authorships and Neo4j Aura Python-driver connectivity and quotas before calling endpoints. API paths, fields, limits and free-tier capacity may change. Use actual responses to confirm assumptions instead of hallucinating them.
4. Inspect credentials **only via environment variables or an ignored local `.env`**. Never require the user to paste them into source code or command-line arguments. Never print, serialize, log, screenshot, send in a report, commit or transmit credentials to any destination other than their intended providers.
5. Define and pin Python dependencies (`pyproject.toml`, a lockfile when possible). Prefer `uv`; if it is unavailable, use `venv` plus documented pip commands. Keep implementation ordinary, readable Python with helpful type hints and small functions. No unnecessary microservices/abstractions.
6. Run a minimum smoke test for **each** external service and record HTTP/driver status, response schema and sanitized error messages. Set connection/request timeouts, retry/backoff and bounded concurrency.

### Required environment variables

Read these from `.env` or the process environment (values intentionally **NOT** included in this prompt):

```dotenv
# Use the existing user's AuraDB instance, not a new paid instance
NEO4J_URI=neo4j+s://<instance>.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<secret>
NEO4J_DATABASE=neo4j
AURA_INSTANCEID=<optional-metadata>
AURA_INSTANCENAME=<optional-metadata>

OPENALEX_API_KEY=<secret>
OPENALEX_BASE_URL=https://api.openalex.org
```

IMPORTANT: The user's environment uses **`NEO4J_USERNAME`**. Accept `NEO4J_USER` as a backwards-compatible fallback, but do not mistakenly treat `NEO4J_USERNAME` as missing. Verify that the Neo4j URI uses `neo4j+s://` and the official driver authenticates with user/password. Keep a checked-in `.env.example` with **placeholders only**, and a `.gitignore` excluding `.env`, alternate env files, credentials, debug dumps and secrets. `OPENALEX_API_KEY` must stay out of URL/query logging and HTTP diagnostics. Scrub secrets before exposing any error to a user.

If credentials are unavailable: implement and fully test all offline features with fixtures; produce `NEEDS_CREDENTIALS.md` listing variable names (never ask conversationally or invent values), and mark real Cloud execution as blocked. If API quotas / network outages prevent completion: resume from cache/checkpoint when possible, retry within limits, preserve partial real results and report the precise blocker. Do **not** substitute fictitious API responses for real data.

### Cloud safety requirements

- Use **only the existing designated Aura instance**. Never buy, upgrade, provision another paid tier, or start a paid job.
- Preflight query: `RETURN 1`, inspect the current labels, relationship types, existing node/edge counts and available resource limits. Confirm via documentation/current console if free-tier quotas differ; plan within the actual instance limits.
- An existing cloud graph might contain unrelated user data: **never run `MATCH (n) DETACH DELETE n`, `DROP DATABASE`, destructive reset, broad delete or drop unrelated constraints/indexes**. Do not overwrite/merge into foreign data on matching human-readable names. If existing nodes conflict with project ownership, do all local validation and stop the conflicting cloud write with a clear blocked status; never wipe to make room.
- Use unique stable IDs and a project/scope identifier such as `scope_id`/`dataset_id` on owned entities where appropriate, while retaining the exact domain labels/types from the architecture. Make project-specific counts distinguishable from existing data. Only insert/upsert owned items.
- Start with a small dry-run/pilot. Use short, bounded batches; retry transient exceptions; make writes **idempotent**, safe to restart and independent of prior partial failures. Verify counts after imports. Never send a large batch blindly to AuraDB Free.
- Consider Neo4j Free storage pressure from storing **full abstract text** and many repeated `paper_ids` arrays; keep data contract and evidence intact, but avoid unbounded property duplication and estimate storage before import. A local structured evidence snapshot remains the ground truth.

## 3. Implement the exact academic data pipeline

### Phase A — fixed source selection and acquisition

Create `configs/scope.yaml` with selected years, ACL/EMNLP volumes, Findings fallback selection rule, arXiv `cat:cs.CL` query/date boundaries, target counts per year/source, stable sorting, deterministic seed, metadata snapshot date and version tags. **Do not cherry-pick papers after seeing graph metrics**; document if expansion is needed. Prefer official ACL Anthology XML/data or the `acl-anthology` Python library rather than indiscriminate HTML scraping. arXiv must use its actual supported API with polite User-Agent, delays and page sizes consistent with official guidance.

Implement `src/data/acl_fetch.py`, `arxiv_fetch.py`, `openalex_enrich.py`. Store raw source metadata, source URLs, timestamps, status, pagination, cache keys and request failures under `data/raw/`, `data/cache/` and a manifest. Add bounded retry with exponential backoff for HTTP 429/5xx, network timeouts and connection resets. Use cache/resume to avoid re-crawling successful work. Do not download thousands of full PDFs: title, abstract, authors, IDs, DOI, venue and paper references are enough.

For OpenAlex enrichment, look up via verified DOI or other **officially supported exact identifier lookups**. Collect `id`, `authorships` with `author`, `author_position`, per-work `institutions`, `referenced_works`, inverted-index abstract and source metadata. Invert `abstract_inverted_index` deterministically when the source abstract is missing; mark provenance. Do not treat an author's `last_known_institutions` as the institution declared on a particular work. Record `unmatched_openalex` and coverage counts. If a work lookup is truncated or ambiguous, use single-work lookup/check raw source; unresolved data belongs in an explicit audit file.

### Phase B — normalization / identity / dedup

Implement `src/data/normalize.py`, `contracts.py`, `topics.py`, `export.py`.

- Canonical IDs: prefer verified OpenAlex `W…`, `A…`, `I…` with `oa:` namespace; use `acl:` or `arxiv:` source IDs when unresolvable. Preserve DOI, arXiv, ACL, ORCID/ROR aliases.
- Deduplicate verified duplicate works. Prefer ACL venue/year for the conference record when same work has a preprint; keep preprint identifiers and source URLs as aliases. Do not automatically merge by close title or author name; send ambiguous cases to `data/rejected/unresolved.csv`.
- Source-only authors can be scoped to their original paper/authorship identity. Never link different authors across papers using only identical names. Do not confuse `author_position` with actual contribution.
- Exclude external citation targets not in this corpus; only create `citing_paper_id → cited_paper_id` when both IDs exist and differ.
- `UNKNOWN` topics and missing affiliation are permitted; do **not** create unsupported relationships just to inflate the graph.

Implement six **rule-based** topic classes exactly as `architecture.md`: `llm`, `mt`, `qa`, `retrieval`, `summarization`, `safety_eval`. Use `title + '\n' + abstract` normalized for matching, preserve original evidence; title match = 2, abstract match = 1, threshold = 2, at most 2 topics. Respect word-boundary, negation/ambiguity and tie rules; unmatched = `UNKNOWN` and **no HAS_TOPIC**. Configurable regex/rules and `rule_version` must be in `configs/topics.yaml`. Validate 50 pilot papers before freezing rules; do not edit rules to cherry-pick the evaluation set. No external LLM required.

### Phase C — **the required data handoff output**

Produce exactly **8 UTF-8 JSONL files** in `data/processed/` **plus** `manifest.json`, per `architecture.md`:

1. `papers.jsonl`: `id,title,year,abstract,doi,acl_id,arxiv_id,source_kind,source_url,venue_id,openalex_id`.
2. `authors.jsonl`: `id,name,orcid,openalex_id,acl_author_id,identity_status`.
3. `institutions.jsonl`: `id,name,ror,country_code,source_url`.
4. `venues.jsonl`: `id,name,kind,year,source_url`.
5. `paper_authors.jsonl`: `paper_id,author_id,position,author_position,source_url`.
6. `affiliations.jsonl`: `paper_id,author_id,institution_id,year,raw_affiliation,source_url`.
7. `citations.jsonl`: `citing_paper_id,cited_paper_id,source_url`.
8. `paper_topics.jsonl`: `paper_id,topic_id,rule_id,evidence_span,confidence_band`.
9. `manifest.json`: `schema_version=1`, `scope_id`, UTC creation time, source version/snapshot, selected/loaded counts, OpenAlex unmatched counts, input/output counts, cryptographic checksums and reproducibility metadata.

**JSONL** means one standalone JSON object per line. Ensure stable ordering, UTF-8, deterministic deduplication, `null` for truly missing facts, correct data types and complete cross-file referential integrity. Validate schema and SHA-256 checksums before any Cloud import. Never mix `data/fixtures/` with actual research records. Make actual processed data available in a compact reproducible snapshot if the license, size and project constraints allow; otherwise document an artifact path and exact rebuild steps.

Implement unit/integration tests for duplicate IDs, paper aliases, author identity collisions, missing authorship endpoints, invalid foreign keys, year out of scope, blank title, unknown topic, citation direction, per-paper affiliation, topic spans, and manifest tampering. Fail clearly and isolate bad records rather than silently patching facts.

## 4. Build and validate Neo4j graph

Five node labels: **`Author`, `Paper`, `Institution`, `Venue`, `Topic`**. Domain attributes and definitions must match `architecture.md`.

Create **exactly these 10 domain relationship types**, no fake inverses/extra types:

| # | Relationship | Meaning/condition |
|---|---|---|
| 1 | `FIRST_AUTHOR_OF` | Author is position 1 on a real paper |
| 2 | `OTHER_AUTHOR_OF` | Author has position > 1 on a real paper |
| 3 | `COAUTHORED_WITH` | Two distinct verified/scoped author IDs appear on same paper; unique canonical unordered pair, evidence paper IDs and shared count |
| 4 | `AFFILIATED_WITH` | Author's institution as explicitly provided **for that paper's authorship**, not current employer; preserve paper/year evidence |
| 5 | `APPEARS_IN` | Paper appeared in an identified conference/preprint venue |
| 6 | `HAS_TOPIC` | Paper topic from evidenced title/abstract rule; max 2 |
| 7 | `CITES` | Directed citation between **two corpus papers**, no self-citation |
| 8 | `ORG_COAUTHORED_WITH` | Different named institutions on one coauthored paper; unique unordered pair with paper evidence |
| 9 | `RESEARCHES` | Author has **≥2 distinct corpus papers** in that topic |
| 10 | `ACTIVE_IN` | Institution associated with **≥2 distinct corpus papers** in that topic |

Important semantic caveats: coauthor != friend; first author != most important; affiliation != present-day employment; organization co-occurrence != business partnership; topic activity != lifetime expertise. Preserve `source_kind`, `source_url` / `evidence_paper_ids`, `evidence_count`, `paper_ids` or equivalent traceable evidence, `build_version`, and years where appropriate. If a >20-author paper would create a huge clique, flag/review per architecture rather than blindly producing quadratic edges.

Implement `src/graph/schema.py`, `load.py`, `derive.py`, `export_authors.py` with the official `neo4j` Python driver:
- Enforce unique `id` constraints per node label using Cypher appropriate for the actual Neo4j version.
- Validate manifest, all source IDs, schema and checksums **before** writes.
- `UNWIND $rows` parameterized upserts via `MERGE` on stable IDs; 200–500 row batches initially, reducing size if Aura throttles. Never interpolate arbitrary relationship-type strings: use a trusted whitelist.
- Nodes first → six direct relation types → four derived relation types. Skip/log dangling endpoint edges into `data/rejected/edges.jsonl`; do **not** let `MERGE` manufacture blank nodes.
- For a repeated author/institution pair or coauthor pair, merge evidence IDs/years deterministically; don't produce parallel edges for repeated papers.
- Include a safe pre-import preview (`--dry-run`), a real authenticated import, and resumable progress markers. Reimport the **same real snapshot** twice and assert counts and per-type evidence remain unchanged. Avoid unrequested deletion or mutation of unrelated data.
- Output actual `COUNT(n)`, `COUNT(r)`, counts by node label and relation type, duplicate/orphan reports, evidence spot checks, and three reproducible Cypher example queries. Prefer snapshot-scoped counts; also show global instance totals separately if preexisting nodes are present.

## 5. Social network analysis (SNA) — Author-only projection

Create a separate undirected **simple** Author–Author graph using `COAUTHORED_WITH` only, export canonical `(min_author_id,max_author_id,shared_count,paper_ids)` pairs and retain isolated Author statistics. Never calculate the collaboration-network small-world property by walking through shared `Topic`, `Venue` or `Institution` nodes.

Implement with NetworkX:
- number of authors, isolates, edges, connected components, LCC size/ratio;
- degree, weighted degree, top 10 authors (with actual evidence papers), degree distribution;
- PageRank top 10 (do not equate it to academic quality);
- Louvain communities with fixed seed, number and modularity, fallback method explicitly labelled if library/version lacks Louvain;
- shortest paths illustrated with paper evidence per collaboration hop;
- LCC clustering coefficient and average shortest path, plus **at least five degree-preserving random graph comparisons** with fixed seeds; output `C_obs`, `L_obs`, `C_rand`, `L_rand`, `sigma` and limitations. If too slow for the free environment, implement bounded/reproducible approximate strategy and clearly label it approximate; don't invent values or declare small-world if evidence is insufficient.

Write results under `output/analysis/` as **real** JSON, CSV and PNG charts; create legible, informative plots and at least one illustrative real subgraph screenshot/export if available. No borrowed results from another group.

## 6. Evidence-based QA and the 90% criterion

Implement `src/evaluation/sample_edges.py`, `score.py` and tests. QA must distinguish **structural validity** from **actual source-supported correctness**:

1. Draw **up to 20 edges per relationship type** using a fixed seed (`20261107`), all edges if fewer; save `evaluation/samples.csv` with endpoints, type, evidence paper IDs, provenance URLs and the source data needed to verify it. Avoid cherry-picked showcase examples.
2. Auto-check every relationship for domain type, endpoints, evidence presence, reference integrity, thresholds, deduplication, direction, and support-paper existence. Create machine-readable `evaluation/structural_checks.json` and invalid-edge samples.
3. Where browsing/source access permits, perform **real source verification** for the sampled edges. Mark each as `correct`, `incorrect` or `unverifiable` only on the basis of traceable source evidence; attach evidence URLs and a reason. An automated verifier is **not equivalent to independent human annotation**. Identify such annotations explicitly as `automated_preliminary`; generate `evaluation/manual_review_template.csv` for independent reviewers and never claim human sign-off unless human labels genuinely exist.
4. For human-confirmed labels if available, or separately for explicitly designated automatically verified labels, calculate per-type precision, macro precision, **graph-count-weighted micro precision**, Wilson 95% intervals and error counts. Unverifiable is never silently correct; conservatively count it as not verified/incorrect while also publishing the separate unverifiable count. Never treat raw `TP / 200` as graph-wide precision for stratified samples with different relation frequencies.
5. Keep all pre-fix and post-fix audit outputs. Fix systematic root causes, regenerate the real graph, take a **fresh controlled sample** and remeasure. Do not fabricate 90% success, grade, CI, labels or review signatures. If 90% remains unverified, state it precisely as a target/pending result.
6. Additional source audits: 40 sampled papers (or source-verifiable maximum), 20 ambiguous author identities, missing abstract/affiliation/references, OpenAlex unmatched rate, duplicate DOI/alias, orphan nodes, citation endpoint coverage and topic `UNKNOWN` rate.

**Do not declare the task complete because 10 relationship type names exist.** All reported counts must represent **actual populated source-supported relationships**, with meaningful provenance. If the real graph does not meet one target, transparently explain why and what valid bounded corpus adjustments could address it.

## 7. CLI, tests and reproducibility

Prefer these exact CLI surfaces; implement and actually run them (adapt options as needed, document deviations):

```bash
uv sync
uv run pytest -q
uv run python -m src.cli fetch --config configs/scope.yaml
uv run python -m src.cli prepare --config configs/topics.yaml
uv run python -m src.cli validate --data data/processed
uv run python -m src.cli import --data data/processed --dry-run
uv run python -m src.cli import --data data/processed
uv run python -m src.cli analyze --out output/analysis
uv run python -m src.cli sample --per-type 20 --seed 20261107
uv run python -m src.cli score --labels evaluation/labels.csv
uv run python -m src.cli report --out report/final.pdf
```

If `labels.csv` is absent or not independently verified, `score` must issue a clearly identified **pending/automated preliminary report**, not pretend manual precision is measured. CLI commands should have helpful `--help`, meaningful exit codes, and log progress without exposing credentials. `scripts/run_all.sh` should orchestrate the real workflow with checkpoints and safe restart; don't blindly force a Cloud re-import on every run.

Minimum tests:
- schema/JSONL contract, checksums, normalization and duplicate/collision cases;
- topic rules positive, negative and ambiguous examples;
- citations only within corpus and with correct direction;
- idempotent graph importer (fixture + real snapshot), unique unordered coauthor pairs;
- all derived edge evidence rules, cross-paper identity isolation;
- source tracing, invalid-edge rejection, QA weighted precision and Wilson CI;
- analysis on tiny deterministic toy graphs including disconnected cases;
- one real smoke run from actual external metadata through Neo4j Aura to final analysis, if environment permits.

For every failed command: **inspect actual stderr/traceback → fix the root cause → rerun the smallest failing test → rerun relevant integration → update logs**. Do not apply arbitrary patches to hide exceptions, alter test expectations just to pass, or silently swallow errors. Use bounded retries for environmental failures and record remaining blockers instead of spinning forever.

## 8. Report and submission artifacts

Write `report/sections/data.md`, `report/sections/graph.md`, and a cohesive **Vietnamese** `report/final.pdf` (at least 10 substantive pages, not blank padding). Include:

1. Instructor assignment, scope, measurable criteria and actual work performed (do not invent team member names or percentages);
2. academic sources, retrieval method, fixed selection and metadata coverage; explicitly explain why Wikipedia is **not the primary source** for precise scientific authorship/citations in this particular topic;
3. full ETL/NLP pipeline and 8 JSONL + manifest schemas with a real, cited paper example;
4. five node labels, ten edge types, semantics and paper-level evidence;
5. technology stack, AuraDB connection method without passwords, important design decisions;
6. actual cloud graph counts, by-type tables, author projection, PageRank/Louvain/path/clustering/small-world comparisons, legible figures;
7. QA sampling protocol, source checks, counts, precision/CI **when justified**, limitations and missing data;
8. what was achieved vs not achieved, known risks, exact runnable commands, GitHub link **only if a real repo/link is available**.

Use any installed **free/offline** PDF production tool you can operate reliably (e.g. Pandoc + engine, Typst, ReportLab), with embedded fonts that render Vietnamese correctly. Inspect the rendered PDF pages, ensure figures/tables aren't clipped, and do not mistake Markdown-to-PDF command success for report quality. If export tooling is unavailable, produce a complete `report/final.md` and record that PDF export is blocked rather than claiming one exists.

Other required artifacts: `README.md` with architecture diagram, prerequisites, environment variable names, data schema, CLI walkthrough, reproducibility, cloud safety, outputs, known limitations; `docs/schema.md`, `docs/sources.md`, `execution_log.md`, `evaluation/`, `output/analysis/`, `data/processed/manifest.json` and sources/snapshots as licensing permits. Optional slide deck only **after** core deliverables work.

Never invent a GitHub link or push to an unverified destination. If a matching configured remote exists and pushing is explicitly authorized by the execution environment, run secret scans and tests before committing/pushing; otherwise leave a clean local repo and instructions to publish it. Do not publish personal access tokens, passwords, `.env`, raw request headers or user private configuration.

## 9. Autonomous execution loop and stopping rules

Do not deliver only a plan. Run this actual sequence:

```text
READ architecture.md + INSPECT REPO
    ↓
VERIFY official APIs + credentials (without revealing secrets)
    ↓
IMPLEMENT fixed data contracts + tests + fixtures
    ↓
FETCH real ACL/arXiv → ENRICH OpenAlex → CACHE
    ↓
NORMALIZE + DEDUP + TOPIC NLP → 8 JSONL + MANIFEST
    ↓
VALIDATE source/data integrity
    ↓
CLOUD PREFLIGHT → DRY RUN → SAFE NEO4J IMPORT
    ↓
RE-IMPORT CHECK (idempotency) + 10-TYPE COUNTS
    ↓
AUTHOR-ONLY ANALYSIS → JSON/CSV/PNG
    ↓
SOURCE QA + ERROR FIXES + RE-EVALUATION
    ↓
WRITE REPORT + README → RENDER/INSPECT PDF
    ↓
RUN TESTS, AUDIT ARTIFACTS, FINAL STATUS
```

Progress states to record in `execution_log.md`: `NOT_STARTED`, `IN_PROGRESS`, `PASSED`, `PARTIAL`, `BLOCKED`, `FAILED`. Record command, exit status, sanitized error, fix, rerun result, output path and precise numerical results. Continue automatically to **independent** remaining tasks if one service is blocked. Do not mark a phase `PASSED` without visible output evidence.

You may automatically choose small implementation details, install ordinary project dependencies in an isolated virtualenv, make normal source-code changes, use public APIs and write to the designated existing Aura project graph under the safeguards above. **Never** pay/upgrade services, destroy unrelated Cloud data, exfiltrate credentials, disable security controls, fabricate evidence, or claim independent human review. No clarification needed for routine decisions. If a non-negotiable external blocker occurs, preserve verified partial work and accurately state it instead of asking repeatedly or improvising fake results.

### Final response format (in Vietnamese)

Report only after doing all feasible work:

```text
IMPLEMENTATION STATUS: PASS / PARTIAL / BLOCKED

Real data: __ unique papers (ACL __, arXiv __), __ authors, __ institutions, __ venues, 6 topic categories
Actual Aura graph: __ nodes, __ unique edges, __/10 populated relation types
Evidence quality: source-audited __ samples, structural __, estimated micro precision __ or NOT VERIFIED, Wilson CI __ or N/A
Tests: __ passed / __ failed; actual commands executed: ...
Artifacts: data/processed/, manifest, output/analysis/, evaluation/, report/final.pdf, README.md
Cloud: instance connected? import finished? idempotency passed? (no secrets)
Unmet targets and reasons: ...
Next action only if a genuine blocker remains: ...
```

**START NOW.** Read the entire `architecture.md` first, inspect the repository, implement both tracks, execute the real pipeline and iteratively fix observed failures until the defensible deliverables are produced. Do not ask me to repeat the requirements, and do not stop at planning or scaffolding.
