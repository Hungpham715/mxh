# Repository audit — 2026-11-13

## Baseline

- Branch `main`, commit `833af8e`; working tree was clean except the three supplied implementation documents.
- Existing `offline/` pipeline is a complete, tracked data/graph pipeline and is intentionally unchanged.
- `offline/.env` exists locally and is ignored. It was not read, copied, logged, or used.
- Local tools: Python 3.12 system / Python 3.13 selected by `uv`, Node 22.22.2, npm 10.9.7, uv 0.11.1.
- Resources observed: about 22 GiB free disk, 15 GiB RAM, NVIDIA RTX 5060 Laptop 8 GiB. This audit does not treat those resources as approval to train.
- Ollama was not available on `PATH`; no live model smoke was claimed.

## Source-of-truth schema

The implementation was checked against `offline/docs/schema.md`, `offline/src/graph/derive.py`,
`offline/src/graph/load.py`, `offline/src/common.py`, `offline/configs/topics.yaml`, and the latest import report.
The snapshot report contains 7,134 scoped nodes and 30,971 scoped relationships across five labels and ten
relationship types. These are artifact counts, not a new live query in this run.

## Change boundary

New product code lives under `chatbot/`. The only existing tracked files changed are `.gitignore` and
`CLAUDE.md`; no offline data, graph loader, report, test, or local secret was modified. External coursework
repositories were shallow-cloned under ignored `references/external/` and never executed.

