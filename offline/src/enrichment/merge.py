"""Merge rule-based and LLM extractions into enrichment entities + edges with provenance.

Merge policy (deterministic, documented):
- LLM surfaces are canonicalized through the gazetteer when possible (resolved_by=gazetteer);
  unknown surfaces get a slug id (resolved_by=slug) and are kept but ranked lower in reports.
- Edges are unique per (type, from_id, to_id) and aggregate evidence across papers, mirroring
  the v1 convention in src/graph/derive.py.
- source_kind = "agreement" when BOTH extractors produced the same edge (highest trust without
  human review), otherwise the name of the single extractor that produced it.
- LLM relations whose endpoint type contradicts the relation schema (e.g. evaluated_on pointing
  at a method) are dropped and counted in stats.drop_reasons.
"""
from __future__ import annotations

from collections import Counter
import re
from typing import Any

from src.enrichment.gazetteer import Gazetteer, slugify
from src.enrichment.schema import (ENRICH_REL_TYPES, ENRICH_VERSION, ENTITY_TYPE_TO_LABEL,
                                   MAX_EVIDENCE_PER_EDGE, best_band, is_generic_surface)

# Relation type -> required entity type of the target (and of the source for entity-entity).
_EXPECTED_TARGET_TYPE = {"USES_METHOD": "method", "ADDRESSES_TASK": "task",
                         "EVALUATED_ON": "dataset", "METHOD_EVALUATED_ON": "dataset"}
_EXPECTED_SOURCE_TYPE = {"METHOD_EVALUATED_ON": "method"}
# Paper-anchored relation implied by mentioning an entity of each type.
_ENTITY_TYPE_TO_PAPER_REL = {"method": "USES_METHOD", "dataset": "EVALUATED_ON",
                             "task": "ADDRESSES_TASK"}


def canonicalize(surface: str, entity_type: str, gazetteer: Gazetteer) -> tuple[str, str]:
    """Resolve an extractor surface to a canonical entity id.

    Returns (entity_id, resolved_by). resolved_by is 'gazetteer' when the curated list knows
    the surface, otherwise 'slug' (id derived mechanically from the surface text).
    """
    gazetteer_id = gazetteer.resolve_surface(surface, entity_type)
    if gazetteer_id is not None:
        return gazetteer_id, "gazetteer"
    return f"{entity_type}:{slugify(surface)}", "slug"


_PAREN_ACRONYM = re.compile(r"\(([A-Z][A-Z0-9-]{1,15})\)")
# A bare trailing acronym is less explicit than a parenthesized one. Require at least four
# characters so ordinary final tokens such as "IRC" in "Ubuntu IRC" are not collapsed.
_TRAILING_ACRONYM = re.compile(r"(?:^|\s)([A-Z][A-Z0-9-]{3,15})$")
_ACRONYM_KIND = re.compile(
    r"^([A-Z][A-Z0-9-]{1,15})\s+"
    r"(?:framework|method|model|algorithm|approach|system|optimization)$",
    re.IGNORECASE,
)
_TYPE_SUFFIX = re.compile(
    r"\s+(?:datasets?|benchmarks?|corpora|corpus|frameworks?|methods?|models?|"
    r"algorithms?|approaches?|systems?)\s*$",
    re.IGNORECASE,
)


def _clean_llm_surface(surface: str) -> str:
    return re.sub(r"\s+", " ", surface).strip(" \t\r\n,;:.")


def _explicit_acronym(surface: str, context: str = "") -> tuple[str, str] | None:
    """Return ``(expanded surface, acronym)`` when the copied text states that mapping."""
    parenthesized = _PAREN_ACRONYM.search(surface)
    if parenthesized:
        expanded = _clean_llm_surface(surface[:parenthesized.start()])
        expanded = _TYPE_SUFFIX.sub("", expanded).strip()
        if expanded:
            return expanded, parenthesized.group(1)

    # The model may copy only the expansion while its evidence still contains the explicit
    # ``expansion (ACRONYM)`` construction. Keep this strictly extractive and adjacency based.
    cleaned_context = _clean_llm_surface(context)
    if surface and cleaned_context:
        pattern = re.compile(
            re.escape(surface) + r"\s*\(([A-Z][A-Z0-9-]{1,15})\)",
            re.IGNORECASE,
        )
        match = pattern.search(cleaned_context)
        if match:
            return _clean_llm_surface(surface), match.group(1)
    return None


def _canonical_llm_surface(surface: str, context: str = "") -> str:
    """Reduce an extractive LLM span to its reusable scientific name.

    Small models often copy a descriptive span instead of the name itself, for example
    ``Ubuntu IRC dataset`` or ``Multi-Turn Safety Alignment (MTSA) framework``.  This
    normalization is deliberately domain-general: it strips only an explicit entity-kind
    suffix and prefers an acronym that is literally present in the copied span.  Evidence
    continues to retain the original verbatim surface.
    """
    cleaned = _clean_llm_surface(surface)
    acronym_pair = _explicit_acronym(cleaned, context)
    if acronym_pair:
        return acronym_pair[1]
    acronym_kind = _ACRONYM_KIND.fullmatch(cleaned)
    if acronym_kind:
        return acronym_kind.group(1)
    cleaned = _TYPE_SUFFIX.sub("", cleaned).strip()
    trailing = _TRAILING_ACRONYM.search(cleaned)
    if trailing and len(cleaned.split()) > 1:
        return trailing.group(1)
    return cleaned


def _canonicalize_llm(
    surface: str,
    claimed_type: str,
    gazetteer: Gazetteer,
    context: str = "",
) -> tuple[str, str, str, str]:
    """Canonicalize an LLM surface and repair a type contradicted by an exact gazetteer hit.

    Returns ``(entity_id, entity_type, resolved_by, display_surface)``.  The claimed type is
    preferred.  Cross-type repair is allowed only when the entire normalized surface matches
    one curated alias, preventing a long descriptive phrase from being relabelled merely
    because it happens to contain a known name.
    """
    cleaned = _clean_llm_surface(surface)
    acronym_pair = _explicit_acronym(cleaned, context)
    # Prefer a curated full expansion over its acronym. This keeps established terms such as
    # "supervised fine-tuning (SFT)" stable while still using the explicit acronym for a newly
    # introduced name that the gazetteer cannot know.
    candidates = [cleaned]
    if acronym_pair:
        candidates.extend(acronym_pair)
    normalized = _canonical_llm_surface(cleaned, context)
    candidates.append(normalized)
    candidates = list(dict.fromkeys(candidate for candidate in candidates if candidate))

    for candidate in candidates:
        entity_id = gazetteer.resolve_surface(candidate, claimed_type)
        if entity_id is not None:
            return entity_id, claimed_type, "gazetteer", candidate

    exact_other = []
    for candidate in candidates:
        for entity_type in ENTITY_TYPE_TO_LABEL:
            if entity_type == claimed_type:
                continue
            entity_id = gazetteer.resolve_surface(candidate, entity_type)
            if entity_id is not None:
                exact_other.append((entity_id, entity_type, candidate))
    if len(exact_other) == 1:
        entity_id, entity_type, candidate = exact_other[0]
        return entity_id, entity_type, "gazetteer", candidate
    return f"{claimed_type}:{slugify(normalized)}", claimed_type, "slug", normalized


class _EntityAcc:
    """Mutable accumulator for one canonical entity across both extractors."""

    def __init__(self, entity_id: str, entity_type: str, name: str, resolved_by: str):
        self.entity_id = entity_id
        self.entity_type = entity_type
        self.name = name
        self.resolved_by = resolved_by
        self.extractors: set[str] = set()
        self.mention_count = 0
        self.papers: set[str] = set()
        self.surfaces: Counter[str] = Counter()
        self.evidence: list[dict[str, Any]] = []

    def add(self, extractor: str, paper_id: str, surface: str, evidence: dict[str, Any] | None,
            mentions: int = 1) -> None:
        self.extractors.add(extractor)
        self.papers.add(paper_id)
        self.surfaces[surface] += mentions
        self.mention_count += mentions
        if evidence is not None and len(self.evidence) < MAX_EVIDENCE_PER_EDGE:
            self.evidence.append({"paper_id": paper_id, "surface": surface, **evidence})

    def record(self) -> dict[str, Any]:
        return {
            "id": self.entity_id, "entity_type": self.entity_type,
            "label": ENTITY_TYPE_TO_LABEL[self.entity_type],
            "name": self.name, "resolved_by": self.resolved_by,
            "extractors": sorted(self.extractors), "mention_count": self.mention_count,
            "n_papers": len(self.papers),
            # Keep the complete membership set separate from the bounded display evidence.
            # Semantic evaluation and downstream provenance must not infer paper coverage from
            # the three-example evidence preview.
            "evidence_paper_ids": sorted(self.papers),
            "aliases": [s for s, _ in self.surfaces.most_common(8)],
            "evidence": sorted(self.evidence, key=lambda e: (e["paper_id"], str(e.get("sentence_index"))))[:MAX_EVIDENCE_PER_EDGE],
        }


class _EdgeAcc:
    """Mutable accumulator for one (type, from, to) edge across papers and extractors."""

    def __init__(self, rel_type: str, from_id: str, to_id: str):
        self.rel_type = rel_type
        self.from_id = from_id
        self.to_id = to_id
        self.extractors: set[str] = set()
        self.bands: list[str] = []
        self.papers: set[str] = set()
        self.years: list[int] = []
        self.evidence: list[dict[str, Any]] = []

    def add(self, extractor: str, band: str, paper_id: str, year: int | None,
            evidence_items: list[dict[str, Any]]) -> None:
        self.extractors.add(extractor)
        self.bands.append(band)
        self.papers.add(paper_id)
        if year is not None:
            self.years.append(year)
        for item in evidence_items:
            self.evidence.append({"paper_id": paper_id, **item})

    def record(self) -> dict[str, Any]:
        papers = sorted(self.papers)
        years = sorted(set(self.years))
        agreement = self.extractors == {"rules", "llm"}
        evidence = sorted(self.evidence, key=lambda e: (e["paper_id"], str(e.get("sentence_index"))))
        return {
            "type": self.rel_type, "from": self.from_id, "to": self.to_id,
            "source_kind": "agreement" if agreement else sorted(self.extractors)[0],
            "extractors": sorted(self.extractors),
            "confidence_band": "agreement" if agreement else best_band(self.bands),
            "verification_status": "unverified",
            "evidence_paper_ids": papers, "evidence_count": len(papers),
            "evidence": evidence[:MAX_EVIDENCE_PER_EDGE],
            "first_year": years[0] if years else None, "last_year": years[-1] if years else None,
            "years": years, "build_version": ENRICH_VERSION,
        }


def merge_all(papers: list[dict[str, Any]], rules_results: list[dict[str, Any]],
              llm_results: list[dict[str, Any]], gazetteer: Gazetteer) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Merge per-paper extractor outputs. Returns (entities, edges_by_type, stats)."""
    paper_by_id = {p["id"]: p for p in papers}
    entities: dict[str, _EntityAcc] = {}
    edges: dict[tuple[str, str, str], _EdgeAcc] = {}
    drop_reasons: Counter[str] = Counter()

    def ensure_entity(entity_id: str, entity_type: str, name: str, resolved_by: str) -> _EntityAcc:
        acc = entities.get(entity_id)
        if acc is None:
            acc = _EntityAcc(entity_id, entity_type, name, resolved_by)
            entities[entity_id] = acc
        return acc

    def ensure_edge(rel_type: str, from_id: str, to_id: str) -> _EdgeAcc:
        key = (rel_type, from_id, to_id)
        acc = edges.get(key)
        if acc is None:
            acc = _EdgeAcc(rel_type, from_id, to_id)
            edges[key] = acc
        return acc

    # ---- rules extractor output (already canonical, gazetteer-resolved)
    for result in rules_results:
        paper_id = result["paper_id"]
        year = (paper_by_id.get(paper_id) or {}).get("year")
        for entity in result["entities"]:
            acc = ensure_entity(entity["entity_id"], entity["entity_type"],
                                entity["canonical_name"], "gazetteer")
            first_evidence = entity["evidence"][0] if entity["evidence"] else None
            surface = first_evidence["surface"] if first_evidence else entity["canonical_name"]
            evidence_item = None
            if first_evidence is not None:
                evidence_item = {"sentence_index": first_evidence.get("sentence_index"),
                                 "evidence_text": first_evidence.get("evidence_text", "")}
            acc.add("rules", paper_id, surface, evidence_item, mentions=entity["n_mentions"])
        for edge in result["edges"]:
            acc = ensure_edge(edge["type"], edge["from"], edge["to"])
            acc.add("rules", edge["confidence_band"], paper_id, year, edge["evidence"])

    # ---- llm extractor output (needs canonicalization + schema type checks)
    llm_failed = 0
    llm_durations: list[int] = []
    for result in llm_results:
        paper_id = result["paper_id"]
        year = (paper_by_id.get(paper_id) or {}).get("year")
        if result.get("error"):
            llm_failed += 1
            continue
        if result.get("duration_ms") is not None:
            llm_durations.append(int(result["duration_ms"]))
        for drop in result.get("drops") or []:
            drop_reasons[str(drop.get("reason"))] += 1

        # surface -> (entity_type, entity_id) for relation endpoint resolution
        surface_ids: dict[str, tuple[str, str]] = {}
        for entity in result.get("entities") or []:
            surface = entity["surface"]
            claimed_type = entity["type"]
            evidence = entity.get("evidence") or {}
            entity_id, entity_type, resolved_by, display_surface = _canonicalize_llm(
                surface, claimed_type, gazetteer, str(evidence.get("evidence_text") or "")
            )
            if resolved_by == "slug" and is_generic_surface(display_surface):
                # Generic noun from the small model ("paper", "model", ...): not an entity.
                drop_reasons["generic_surface"] += 1
                continue
            known = gazetteer.entries.get(entity_id)
            name = known.canonical_name if known else display_surface
            acc = ensure_entity(entity_id, entity_type, name, resolved_by)
            acc.add("llm", paper_id, surface,
                    {"sentence_index": evidence.get("sentence_index"),
                     "evidence_text": evidence.get("evidence_text", "")})
            surface_ids[surface.strip().lower()] = (entity_type, entity_id)

        for relation in result.get("relations") or []:
            rel_type = relation["rel"]
            to_surface = relation["to_surface"].strip()
            to_info = surface_ids.get(to_surface.lower())
            if to_info is None:
                drop_reasons["endpoint_not_extracted"] += 1
                continue
            to_type, to_id = to_info
            if to_type != _EXPECTED_TARGET_TYPE[rel_type]:
                drop_reasons["endpoint_type_mismatch"] += 1
                continue
            if rel_type == "METHOD_EVALUATED_ON":
                from_surface = relation["from_surface"].strip()
                from_info = surface_ids.get(from_surface.lower())
                if from_info is None or from_info[0] != _EXPECTED_SOURCE_TYPE[rel_type]:
                    drop_reasons["endpoint_type_mismatch"] += 1
                    continue
                from_id = from_info[1]
            else:
                from_id = paper_id
            acc = ensure_edge(rel_type, from_id, to_id)
            evidence = relation.get("evidence") or {}
            acc.add("llm", "llm_extracted", paper_id, year,
                    [{"sentence_index": evidence.get("sentence_index"),
                      "evidence_text": evidence.get("evidence_text", "")}])

        # Mention-implies-link (same semantics as the rules extractor): every LLM-extracted
        # entity also produces its paper-anchored edge, unless an explicit relation above
        # already recorded the LLM for that exact edge.
        for entity in result.get("entities") or []:
            info = surface_ids.get(entity["surface"].strip().lower())
            if info is None:
                continue  # entity was dropped (generic surface); no edge either
            entity_type, entity_id = info
            rel_type = _ENTITY_TYPE_TO_PAPER_REL.get(entity_type)
            if rel_type is None:
                continue
            existing = edges.get((rel_type, paper_id, entity_id))
            if existing is not None and "llm" in existing.extractors:
                continue
            acc = ensure_edge(rel_type, paper_id, entity_id)
            evidence = entity.get("evidence") or {}
            acc.add("llm", "llm_extracted", paper_id, year,
                    [{"sentence_index": evidence.get("sentence_index"),
                      "evidence_text": evidence.get("evidence_text", "")}])

    entity_records = sorted((acc.record() for acc in entities.values()), key=lambda r: r["id"])
    edges_by_type: dict[str, list[dict[str, Any]]] = {t: [] for t in ENRICH_REL_TYPES}
    for (rel_type, _from, _to), acc in edges.items():
        edges_by_type[rel_type].append(acc.record())
    for rel_type in edges_by_type:
        edges_by_type[rel_type].sort(key=lambda e: (e["from"], e["to"]))

    stats = {
        "papers": len(papers),
        "entities_total": len(entity_records),
        "entities_by_type": dict(Counter(r["entity_type"] for r in entity_records)),
        "entities_by_resolved_by": dict(Counter(r["resolved_by"] for r in entity_records)),
        "edges_total": sum(len(v) for v in edges_by_type.values()),
        "edges_by_type": {t: len(v) for t, v in edges_by_type.items()},
        "edges_by_source_kind": dict(Counter(e["source_kind"] for v in edges_by_type.values() for e in v)),
        "edges_by_confidence_band": dict(Counter(e["confidence_band"] for v in edges_by_type.values() for e in v)),
        "llm": {
            "results": len(llm_results), "failed": llm_failed,
            # A resumable run may legitimately reuse records produced before a decoding-only
            # extractor revision (for example a lower output-token ceiling). Preserve that
            # provenance explicitly so the merged snapshot remains reproducible and auditable.
            "extractor_versions": dict(sorted(Counter(
                str(result.get("extractor_version") or "unknown") for result in llm_results
            ).items())),
            "models": dict(sorted(Counter(
                str(result.get("model") or "unknown") for result in llm_results
            ).items())),
            "mean_duration_ms": round(sum(llm_durations) / len(llm_durations)) if llm_durations else None,
            "drop_reasons": dict(drop_reasons.most_common()),
        },
        "top_unresolved_surfaces": [
            {"id": r["id"], "name": r["name"], "n_papers": r["n_papers"]}
            for r in sorted((r for r in entity_records if r["resolved_by"] == "slug"),
                            key=lambda r: (-r["n_papers"], r["id"]))[:15]
        ],
    }
    return entity_records, edges_by_type, stats
