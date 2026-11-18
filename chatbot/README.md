# MXH NLP Graph Atlas

Graph-only chatbot for the existing `nlpgraph-v1` author/paper/institution/topic graph. Qwen parses an allowed
action and writes from verified graph facts; Python owns entity linking, Cypher selection, limits, evidence, and
citations. Fake mode runs the whole product deterministically and is visibly labelled simulated.

## See the UI now

```bash
cd chatbot
cp .env.example .env
bash scripts/setup.sh
bash scripts/check_env.sh
bash scripts/smoke_fake.sh
bash scripts/dev.sh
```

Open `http://127.0.0.1:5173`. The UI includes local conversation history, cancel, evidence, query trace, dark
mode, mobile layout, ambiguity candidates, and POST SSE with non-stream fallback.

## Quality gates

```bash
uv run pytest -q
uv run ruff check .
npm --prefix ui run test
npm --prefix ui run build
bash scripts/eval_synthetic.sh
uv run python training/train_sft.py --dry-run --config training/config_sft.yaml
```

## Switch to Aura + Ollama

Install/pull Ollama, create a real read-only Aura user, and fill Profile B in `.env`. Then run
`bash scripts/smoke_neo4j.sh` and `bash scripts/smoke_ollama.sh`. Real failures are returned explicitly; no fake
answer is substituted. See `docs/EXTERNAL_DEPENDENCIES.md` and `docs/OPERATIONS.md`.

## Dataset → review → SFT → evaluation

```bash
uv run python -m datasets.generate_from_graph --provider neo4j --execute --per-action 600 --limit 12000 --snapshot-version processed-manifest-sha256:<sha256> --out data/generated/live_candidates.jsonl
uv run python -m datasets.auto_review --provider neo4j --execute --input data/generated/live_candidates.jsonl --out data/generated/silver_review.csv
uv run python -m datasets.import_review --source data/generated/live_candidates.jsonl --csv data/generated/silver_review.csv --status-on-yes silver_approved --out data/reviewed/silver.jsonl --rejected data/reviewed/silver_rejected.jsonl
uv run python -m datasets.split --input data/reviewed/silver.jsonl --out data/splits/silver.jsonl
uv run python -m datasets.audit_dataset --input data/splits/silver.jsonl --json data/splits/manifest.json --markdown data/splits/quality_audit.md
uv run python -m datasets.build_sft --reviewed data/splits/silver.jsonl --out data/splits/sft.jsonl --manifest data/splits/sft.manifest.json
uv run python training/train_sft.py --dry-run --dataset data/splits/sft.jsonl --config training/config_sft.yaml
uv run python -m evaluation.run_eval --dataset data/splits/silver.jsonl --allow-silver --provider ollama --graph neo4j --max-iterations 5 --output-dir reports/eval/B1_silver
```

For independent human gold, use `datasets.export_review` and import the completed sheet without
`--status-on-yes silver_approved`. Training is optional, GPU-gated, and uses only reviewed train/validation data. The Colab notebook calls the same
training engine and never uploads automatically. The local PEFT adapter runs via `hf_cpu`, not Ollama. Synthetic
reports carry a non-benchmark banner; official comparison requires the same held-out reviewed test set.

