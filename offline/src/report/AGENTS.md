# Agent scope: `offline/src/report`

This file applies to the established offline graph pipeline at `offline/src/report` and all descendants unless a nearer `AGENTS.md` overrides it.

- Inherit the repository rules in `/AGENTS.md`.
- Preserve its contracts and generated-data boundaries; run offline tests for any code change here.
- Preserve unrelated and ignored local work; never print, commit, or invent secrets.
- Keep changes minimal, validate the narrow scope, and report skipped external gates as `NOT RUN`.
