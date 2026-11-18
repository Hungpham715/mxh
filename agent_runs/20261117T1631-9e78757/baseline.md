# Baseline audit — run 20261117T1631-9e78757

Base SHA 9e78757 ("Add chatbot product + SFT pipeline; replace graph-eval CI with reliable-kg-estimation").
Labels: OBSERVED_LIVE (ran this session) / FROM_REPO_ARTIFACT (file in repo, not re-verified live) / ASSUMED / NOT_VERIFIED.

## Tests & builds (all OBSERVED_LIVE, this session)

| Check | Command | Result |
|---|---|---|
| offline tests | `cd offline && uv sync && uv run python -m pytest -o addopts='' -q` | **72 passed** in 1.15s |
| chatbot tests | `cd chatbot && uv sync && uv run pytest -q` | **53 passed** |
| chatbot lint | `uv run ruff check .` | **All checks passed** |
| UI tests | `cd chatbot/ui && npm run test` | **2 passed** (1 file) |
| UI build | `npm run build` | **OK** (tsc + vite, 362.74 kB bundle) |
| env profile | `bash scripts/check_env.sh` | profile `real/neo4j/ollama`; NEO4J_*/HF/LangSmith configured; **ollama_service unreachable** (exit 1) |
| Aura smoke | `bash scripts/smoke_neo4j.sh` | **FAIL**: `Neo4j unavailable: ServiceUnavailable` (instance paused — see preflight) |

## Snapshot facts

- Processed data (OBSERVED_LIVE wc -l): papers 1091, authors 5430, institutions 600, venues 7, affiliations 4764, paper_authors 6098, paper_topics 451, citations 26. Manifest 2026-11-03, scope nlpgraph-v1, ACL 840 + arXiv 252 selected, OpenAlex 1090/1092 matched.
- Graph counts (FROM_REPO_ARTIFACT offline/output/analysis/graph_counts.json, 2026-11-03): 7134 nodes, 30971 rels, all 10 types populated; author identity: 4691 verified / 712 source_only / 27 unresolved. Live re-count from Aura **BLOCKED** (instance paused).
- **Derived edge files in `offline/data/derived/` at HEAD are 3-8-row TEST FIXTURES (oa:AFIX1), not the real graph** (OBSERVED_LIVE + git show). Real derived edges are regenerated in-memory by `src.graph.load.run_import`/`derive_edges` from processed tables; no full derived snapshot is committed. Any "count the derived JSONL" audit must first regenerate from processed data deterministically.
- chatbot artifacts from 2026-11-14 session (FROM_REPO_ARTIFACT, NOT_VERIFIED against live services): data/generated/all_candidates.jsonl 2024 rows, reviewed/approved.jsonl 2023 rows (auto-review — not human gold), splits/sft.jsonl 2803 samples (messages format, assistant_only_loss=true, sha256 8bffdb4b…), splits/test.jsonl 300 rows, trained LoRA adapter at chatbot/data/models/qwen3-06b-graphrag-lora (checkpoint-411 final).
- `chatbot/docs/ACCEPTANCE_REPORT.md` (2026-11-13, FROM_REPO_ARTIFACT): fake PASS; Aura/Ollama/B2 adapter/SFT all NOT RUN at that time.
- offline/evaluation (FROM_REPO_ARTIFACT): automated_labels_postfix.csv + compute_precision.py (auto estimate ~88.95% — **not human gold**), review sheets round1 (150+30) unlabeled by humans, kg_accuracy.py vendored (Wilson/Agresti-Coull + stratified ESS per project memory).

## Bug list from prompt.md §1 re-verified at HEAD

The prompt's 2026-11-14 audit list must be checked, not copied. Verification plan (results recorded in later phase notes):

1. Workflow fixed plan vs dynamic replanning — inspect `chatbot/src/graphrag/workflow.py`, `planner.py`, `sufficiency.py`. NOT_VERIFIED yet.
2. `LIMIT 20` causing false `complete=true` — inspect cypher_templates + evidence normalization. NOT_VERIFIED yet.
3. localStorage history not reaching backend — inspect api.py request model + UI client. NOT_VERIFIED yet.
4. SSE replayed after workflow.run — inspect api.py stream endpoint. NOT_VERIFIED yet (2026-11-13 acceptance report claims 8 live SSE event types were observed, so this may already be fixed).
5. metrics.py hardcoded `json_validity=1.0` / not_measured — inspect evaluation/metrics.py. NOT_VERIFIED yet.
6. 12 synthetic candidates ≠ large SFT — CONFIRMED still relevant at artifact level (synthetic dir = 24K, 12 cases) but live generated set is now 2024 (FROM_REPO_ARTIFACT).
7. Notebook SFT schema prompt/completion vs messages — inspect training/notebooks + train_sft.py. sft.jsonl manifest says format=chat_messages, so exporter may be fixed; notebook NOT_VERIFIED.

## Environment gaps

- Ollama not installed (G5 blocker; user-space install being attempted in PHASE B).
- Aura instance paused (G4/G7 hard blocker; owner must resume at console.neo4j.io — cannot be done without login).
- /home disk 4.5G free: all downloads staged via /tmp (16G free).

## Immediate action plan (PHASE B onwards)

1. B: install Ollama user-space (bin + CPU runners only), pull qwen3:0.6b, run real router/answer probes; keep Aura BLOCKED with retry probe each phase.
2. B': stand up local Neo4j Community (user-space, Java 21 present) as clearly-labelled NOT-Aura real graph target; import processed snapshot via reviewed offline importer into scope nlpgraph-v1; enables real chatbot E2E + dataset generation while Aura is paused. G4 remains BLOCKED regardless.
3. C: regenerate derived edges deterministically; verify snapshot vs 2026-11-03 counts; decide if source expansion needed for 10k candidates (disk-aware).
4. D: full integrity audit on regenerated graph (100% nodes/edges) + stratified truth sampling with independent review queue (G3 stays BLOCKED without human reviewer; produce all tooling + silver_auto only).
5. E: verify/fix the 7 suspected bugs at HEAD with tests.
6. F: scale generation toward >=10k candidates / >=6k silver from live graph data; leakage-checked splits.
7. G: benchmark runner with real provider (Ollama/hf_cpu+adapter) on local real DB; B2=SFT adapter available locally — can run as real inference (CPU), labelled accordingly.
8. H: report, docs, undone.md maintenance, secret scan, commit, push branch.
