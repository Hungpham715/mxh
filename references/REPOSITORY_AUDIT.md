# External repository audit

All repositories below were shallow-cloned read-only on 2026-11-13 into ignored `references/external/`.
No code was executed or copied. No repository had a license file at its root, so this project uses only
architectural observations and independently written code.

| Team | URL | Branch | Commit inspected | Main files inspected | Finding used |
|---|---|---|---|---|---|
| 04 | https://github.com/manhperas/graph_repo | `dev` | `b6b6c7f558967a056153c0547fc5d5c5ee1d41df` | README, `src/` inventory | ETL/NetworkX reference only; no GraphRAG runtime |
| 05 | https://github.com/Nhungnguyen0804/vn-actors-directors-network | `main` | `7b7c7bc9e498e05c6970761fc1d17bacbe2cc0a6` | `src/api.py`, `model_v2.py`, entity linker, graph query | Keep deterministic intent/query boundary and trace; avoid wildcard CORS/global model races |
| 06 | https://github.com/giakhanh22024558/Social-Network-Analysis | `master` | `e2c636989afa949d5dd669f35e2b963751a547a7` | iterative RAG and web backend | Keep bounded iterative retrieval; replace substring sufficiency/full-text search/hardcoded secrets |
| 07 | https://github.com/lh6104/VNFootballGraph | `main` | `ecd13eabcc445fa118671dc96cb901beecbc277b` | README/source inventory | Checkpoint/resume ideas only |
| 08 | https://github.com/SnowflakeTech/EPL-Wiki-Football | `main` | `2e4e1b384b2248d734658f8721e7056badd60b6d` | README/source inventory | Schema/path caution only |
| 09 | https://github.com/datmieu204/political-net | `main` | `368ab41328a3d4bc81573acf2167c403b3d880b2` | graph state/nodes/workflow, vector index, API | Keep inspectable state/loop; reject vector retrieval, import-time service init, broad Cypher and TF/MCQ-only output |
| 13 | https://github.com/tlam25/network-of-awards-and-winners | `main` | `c51909a3634773b0bb76710d4029053173ab311e` | README/source/notebook inventory | Separate graph enrichment training from chatbot training/evaluation |

The team 6 checkout is newer than the commit recorded in `references/team_6.md`; the local audit records the
actual inspected commit rather than silently treating the older note as current.

