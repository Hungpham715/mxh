"""Curated-gazetteer loading and surface-form matching for the rule-based NER baseline.

Pattern status:
- Type: custom design choice for this project (a dictionary/gazetteer NER baseline is a
  standard technique, but this exact structure is project-specific).
- Why used: deterministic, auditable entity recognition with zero ML dependencies; every
  match can be traced back to a curated alias and a character span.
- Trade-off: only recognizes entities present in the curated list (recall ceiling); the LLM
  extractor in extract_llm.py exists to complement it.

Matching rules (all deterministic):
- Aliases are matched with word-boundary lookarounds, longest alias first, so "GPT-4" wins
  over "GPT" and "CNN/DailyMail" wins over "CNN".
- Entries flagged case_sensitive=True only match their exact capitalization. This protects
  against common-word collisions ("opt", "drop", "whisper", "llama", ...).
- Overlapping matches are skipped: once a character span is claimed by a longer alias,
  shorter aliases cannot match inside it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ENTITY_TYPES = ("method", "dataset", "task")
# Section name in gazetteer.yaml -> entity type. Plural keys map to the singular type name.
_SECTION_TYPES = {"methods": "method", "datasets": "dataset", "tasks": "task"}


def slugify(name: str) -> str:
    """Convert a display name to a stable id fragment: 'GPT-3.5' -> 'gpt-3-5'."""
    lowered = name.lower()
    replaced = re.sub(r"[^a-z0-9]+", "-", lowered)
    return replaced.strip("-")


@dataclass(frozen=True)
class GazetteerEntry:
    """One curated entity: id like 'method:bert', canonical display name, match policy."""
    entity_id: str
    entity_type: str
    canonical_name: str
    case_sensitive: bool


@dataclass(frozen=True)
class AliasPattern:
    """One compiled surface form belonging to one entry."""
    alias: str
    entry: GazetteerEntry
    regex: re.Pattern[str]


@dataclass(frozen=True)
class Mention:
    """A gazetteer hit inside a text: what matched, where, and which entity it resolves to."""
    entity_id: str
    entity_type: str
    canonical_name: str
    surface: str
    start: int
    end: int


def _build_regex(alias: str, case_sensitive: bool) -> re.Pattern[str]:
    # Lookarounds instead of \b: \b behaves inconsistently for aliases that start/end with a
    # non-word character (e.g. "FLORES+"). (?<!\w)/(?!\w) means "not adjacent to a letter/digit".
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.compile(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", flags)


def _parse_entry(raw: Any, entity_type: str) -> tuple[GazetteerEntry, list[str]]:
    """Accept either a plain string ('BERT') or a mapping with aliases/case_sensitive/id."""
    if isinstance(raw, str):
        name = raw
        aliases = [raw]
        case_sensitive = False
        explicit_id = None
    elif isinstance(raw, dict):
        name = str(raw["name"])
        aliases = list(raw.get("aliases") or [name])
        # Some canonical display names are broader than safe match surfaces (for example
        # "Dialogue" versus "task-oriented dialogue").
        if bool(raw.get("match_name", True)) and name not in aliases:
            aliases.append(name)
        case_sensitive = bool(raw.get("case_sensitive", False))
        explicit_id = raw.get("id")
    else:
        raise ValueError(f"gazetteer entries must be str or mapping, got {type(raw).__name__}")
    slug = explicit_id or slugify(name)
    entry = GazetteerEntry(entity_id=f"{entity_type}:{slug}", entity_type=entity_type,
                           canonical_name=name, case_sensitive=case_sensitive)
    return entry, aliases


class Gazetteer:
    """All curated entries plus their compiled alias patterns, longest-first."""

    def __init__(self, entries: dict[str, GazetteerEntry], patterns: list[AliasPattern], version: str):
        self.entries = entries
        self.patterns = patterns
        self.version = version

    @classmethod
    def from_file(cls, path: Path) -> "Gazetteer":
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        version = str(data.get("gazetteer_version", "unknown"))
        entries: dict[str, GazetteerEntry] = {}
        patterns: list[AliasPattern] = []
        for section, entity_type in _SECTION_TYPES.items():
            for raw in data.get(section) or []:
                entry, aliases = _parse_entry(raw, entity_type)
                if entry.entity_id in entries:
                    raise ValueError(f"duplicate gazetteer id: {entry.entity_id}")
                entries[entry.entity_id] = entry
                for alias in aliases:
                    patterns.append(AliasPattern(alias, entry, _build_regex(alias, entry.case_sensitive)))
        if not entries:
            raise ValueError(f"gazetteer is empty: {path}")
        # Deterministic order: longest alias first (specific beats generic), ties by alias text.
        patterns.sort(key=lambda p: (-len(p.alias), p.alias))
        return cls(entries, patterns, version)

    def match_text(self, text: str) -> list[Mention]:
        """Return non-overlapping mentions in text, ordered by position.

        Longest aliases are matched first and claim their character span; a shorter alias
        overlapping a claimed span is skipped. This makes "GPT-4" win over "GPT".
        """
        claimed = bytearray(len(text))  # 0 = free, 1 = already part of a longer mention
        mentions: list[Mention] = []
        for pattern in self.patterns:
            for match in pattern.regex.finditer(text):
                start, end = match.span()
                if any(claimed[start:end]):
                    continue
                for i in range(start, end):
                    claimed[i] = 1
                mentions.append(Mention(
                    entity_id=pattern.entry.entity_id,
                    entity_type=pattern.entry.entity_type,
                    canonical_name=pattern.entry.canonical_name,
                    surface=match.group(0),
                    start=start,
                    end=end,
                ))
        mentions.sort(key=lambda m: (m.start, m.end))
        return mentions

    def resolve_surface(self, surface: str, entity_type: str) -> str | None:
        """Map a surface form (e.g. from the LLM extractor) to a curated entity id, if known.

        Resolution is exact over the complete surface. ``match_text`` intentionally finds
        aliases embedded in prose, but using that behaviour here would collapse a more specific
        extracted name to a shorter alias (for example ``GPT-3.5-turbo`` to ``GPT-3.5`` or
        ``machine translation evaluation`` to ``machine translation``).

        Returns None when the complete surface is not in the gazetteer; the caller then falls
        back to a slug-based id and records resolved_by='slug' (lower trust).
        """
        mentions = self.match_text(surface)
        for mention in mentions:
            if (
                mention.entity_type == entity_type
                and mention.start == 0
                and mention.end == len(surface)
            ):
                return mention.entity_id
        return None
