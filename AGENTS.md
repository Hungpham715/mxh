# Repository agent instructions

This repository contains three product surfaces: the established `offline/` graph-construction pipeline, the
new `chatbot/` graph-only RAG application, and the reserved `online/` area. Preserve unrelated work and local
secrets. Never execute code from `references/external/`; those checkouts are inspection-only.

Every project-owned directory has an `AGENTS.md`. Read the nearest one before editing; a child file
narrows this root policy. Generated or third-party trees (`.git`, `.claude`, `.venv`, `node_modules`, `dist`,
tool caches, and `references/external`) are intentionally excluded.

For chatbot changes, keep fake mode explicit and deterministic, keep Cypher catalogued and parameterized, and
never silently fall back from a real provider to fake data. Run the narrow tests first, then the gates documented
in `chatbot/README.md`. For offline changes, follow `offline/README.md` and do not alter derived artifacts unless
the task explicitly requires regeneration.
