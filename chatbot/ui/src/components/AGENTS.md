# Agent scope: `chatbot/ui/src/components`

This file applies to the graph-only chatbot application at `chatbot/ui/src/components` and all descendants unless a nearer `AGENTS.md` overrides it.

- Inherit the repository rules in `/AGENTS.md`.
- Use fake mode for local gates. Keep real-provider failures explicit, Cypher read-only, and evidence server-derived.
- Preserve unrelated and ignored local work; never print, commit, or invent secrets.
- Keep changes minimal, validate the narrow scope, and report skipped external gates as `NOT RUN`.
