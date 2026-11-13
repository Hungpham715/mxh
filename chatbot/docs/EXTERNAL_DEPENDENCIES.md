# External dependencies and profiles

## A — fake local

No account, secret, model, database, GPU, LangSmith, or paid API is required. Install Python/uv and Node/npm,
copy `.env.example` to `.env`, keep the three fake values, then run `bash scripts/dev.sh`.

## B — live CPU base

Requires a Neo4j Aura connection and a database user with actual read-only privileges, plus local Ollama:

```bash
ollama pull qwen3:0.6b
ollama serve
```

Set the Profile B variables in local `.env`. `execute_read()`/read routing improves routing but is not an access
control boundary; database permissions must also prevent writes. Aura TLS URIs normally use `neo4j+s://`.

## C — live CPU local adapter

Install `uv sync --extra hf`, set `LLM_PROVIDER=hf_cpu`, the public Qwen model ID, and an absolute local
`MODEL_ADAPTER_PATH`. The base model may download once. Ollama does not load PEFT adapters automatically.

## Status meanings

- `configured`: required input/tool exists.
- `missing`: required input for the selected profile is absent.
- `optional`: unrelated to the selected profile.
- `unreachable`: configured endpoint failed a bounded reachability check.

`scripts/check_env.py` never prints URI credentials, passwords, tokens, or adapter content. Hugging Face tokens
are optional for public downloads and LangSmith is disabled by default. Qdrant, Chroma, FAISS, Elasticsearch,
Redis, Postgres, paid LLMs, and analytics are not part of this product.

