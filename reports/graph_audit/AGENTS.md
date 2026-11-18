# Agent scope: `reports/graph_audit`

This file applies to repository support files at `reports/graph_audit` and all descendants unless a nearer `AGENTS.md` overrides it.

- Inherit the repository rules in `/AGENTS.md`.
- Keep automation deterministic, secret-safe, and usable from the repository root.
- Preserve unrelated and ignored local work; never print, commit, or invent secrets.
- Keep changes minimal, validate the narrow scope, and report skipped external gates as `NOT RUN`.
