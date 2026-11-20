# Real GraphRAG demo runbook

This demo uses the read-only Aura base graph (`nlpgraph-v1`), additive text-mining scope
(`nlpgraph-enrich-v1`), and local `qwen3:0.6b`. It never substitutes fake facts when either provider fails.
Run it from `chatbot/`.

## Preflight

```bash
bash scripts/check_env.sh
bash scripts/smoke_neo4j.sh
bash scripts/smoke_ollama.sh
```

The expected inventory is 7,134 nodes and 30,971 relationships. Stop if `/api/health` is degraded or the
inventory differs; do not present fake-mode output as research evidence.

## Capture the eight evidence cases

```bash
uv run python scripts/capture_real_demo.py --out reports/demo
```

The script records no credentials. `real_trace.jsonl` stores the full answer, citations, query trace, decisions,
iteration count, model/provider metadata, and wall latency for:

1. direct author-to-paper retrieval;
2. a known two-hop path (`Xipeng Qiu -> Xuanjing Huang -> Tao Gui`);
3. an author profile that requires successive paper and affiliation queries;
4. a coauthor-plus-affiliation traversal;
5. a missing-entity case that must not invent papers.
6. Paper → `USES_METHOD` → Method retrieval from abstract-mined evidence;
7. Method → Paper retrieval with a publication-year filter;
8. Method ranking by database-derived distinct-paper count for 2025.

`summary.json` is the compact provenance and p50/p95 latency artifact. Inspect every evidence paper ID before a
live presentation because the model wording can vary even though graph facts are server-derived.

The packaged offline fallback is `reports/demo/atlas.png` together with `real_trace.jsonl` and `summary.json`.
Only these bounded, credential-free demo artifacts are versioned; other generated reports remain ignored.

## Interactive UI

```bash
bash scripts/dev.sh
```

Open `http://127.0.0.1:5173`. Use **Atlas** for the real offline SNA snapshot and **Chat** for the live provider
workflow. The fake banner applies only when the configured chat profile is fake; Atlas declares its own snapshot
provenance.
