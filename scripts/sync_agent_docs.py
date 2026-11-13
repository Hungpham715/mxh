#!/usr/bin/env python3
"""Create AGENTS.md in every project-owned directory."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {
    ".git",
    ".claude",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
}


def excluded(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return True
    return len(relative.parts) >= 2 and relative.parts[:2] == ("references", "external")


def area_for(relative: Path) -> tuple[str, str]:
    if relative == Path("."):
        return (
            "the whole GraphRAG repository",
            "Read AGENTS.md. Keep offline, chatbot, online, and inspection-only references separated.",
        )
    first = relative.parts[0]
    if first == "chatbot":
        return (
            "the graph-only chatbot application",
            "Use fake mode for local gates. Keep real-provider failures explicit, Cypher read-only, "
            "and evidence server-derived.",
        )
    if first == "offline":
        return (
            "the established offline graph pipeline",
            "Preserve its contracts and generated-data boundaries; run offline tests for any code "
            "change here.",
        )
    if first == "references":
        return (
            "the read-only reference audit",
            "Record provenance and findings only. Never execute or copy external repository code wholesale.",
        )
    if first == "design-system":
        return (
            "the UI design-system record",
            "Keep decisions consistent with the implemented local-font, accessible chat interface.",
        )
    if first == "online":
        return (
            "the reserved online workspace",
            "Do not add deployment code or credentials without an explicit deployment task.",
        )
    return (
        "repository support files",
        "Keep automation deterministic, secret-safe, and usable from the repository root.",
    )


def content(directory: Path) -> str:
    relative = directory.relative_to(ROOT)
    display = "." if relative == Path(".") else relative.as_posix()
    area, instruction = area_for(relative)
    return f"""# Agent scope: `{display}`

This file applies to {area} at `{display}` and all descendants unless a nearer `AGENTS.md` overrides it.

- Inherit the repository rules in `/AGENTS.md`.
- {instruction}
- Preserve unrelated and ignored local work; never print, commit, or invent secrets.
- Keep changes minimal, validate the narrow scope, and report skipped external gates as `NOT RUN`.
"""


def main() -> None:
    directories = [ROOT]
    directories.extend(path for path in ROOT.rglob("*") if path.is_dir() and not excluded(path))
    owned = sorted(set(directories))
    for directory in owned:
        legacy = directory / "agent.md"
        legacy.unlink(missing_ok=True)
        if directory != ROOT:
            (directory / "AGENTS.md").write_text(content(directory), encoding="utf-8")
    print(f"synchronized {len(owned)} AGENTS.md files")


if __name__ == "__main__":
    main()
