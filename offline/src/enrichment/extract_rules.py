"""Rule-based NER + RE extractor over paper abstracts (deterministic dictionary baseline).

Workflow per paper:
1. Gazetteer matching finds entity mentions (method/dataset/task) with exact character spans.
2. Each mention is attached to its sentence -> that sentence is the evidence text.
3. Relations are emitted in two shapes:
   - Paper-anchored: USES_METHOD / EVALUATED_ON / ADDRESSES_TASK for every mentioned entity.
   - Entity-to-entity: METHOD_EVALUATED_ON when a single sentence mentions a method AND a
     dataset AND contains an evaluation cue verb ("evaluate", "test", "benchmark", ...).
4. Every edge carries a confidence band: rule_high when a cue verb appears in an evidence
   sentence, otherwise rule_medium (plain mention / co-occurrence).

Pattern status: project convention — the edge record shape mirrors src/graph/derive.py
(evidence_paper_ids, confidence_band, source_kind) so downstream tooling stays uniform.
"""
from __future__ import annotations

import re
from typing import Any

from src.enrichment.gazetteer import Gazetteer, Mention, slugify
from src.enrichment.schema import MAX_EVIDENCE_PER_EDGE, is_generic_surface
from src.enrichment.textutil import Sentence, split_sentences, sentence_at

EXTRACTOR = "rules"

# Cue-verb lexicons. These decide the confidence band, not whether an edge exists
# (except METHOD_EVALUATED_ON, which requires an evaluation cue for precision).
USE_CUES = re.compile(
    r"\b(use[sd]?|using|employ\w*|appl(?:y|ies|ied|ication)|adopt\w*|propos\w+|introduc\w+"
    r"|extend\w*|build\w*|based on|fine-?tun\w*|train\w*)\b", re.IGNORECASE)
EVAL_CUES = re.compile(
    r"\b(evaluat\w+|assess\w+|tests?|tested|testing|benchmark\w*|experiment\w*|compar\w+"
    r"|measur\w+|achiev\w+|outperform\w+|performance|results?)\b", re.IGNORECASE)
TASK_CUES = re.compile(
    r"\b(tasks?|problems?|applications?|address\w*|focus\w*|target\w*|aims?)\b", re.IGNORECASE)

# entity type -> (paper-anchored relation type, cue lexicon)
_TYPE_TO_RELATION = {
    "method": ("USES_METHOD", USE_CUES),
    "dataset": ("EVALUATED_ON", EVAL_CUES),
    "task": ("ADDRESSES_TASK", TASK_CUES),
}

# Product/model names change much faster than a curated gazetteer. These conservative patterns
# recover explicit scientific naming constructions while staying fully extractive. They do not
# contain names from the evaluation slice.
_NAME = r"[A-Z][A-Za-z0-9]*(?:[-.][A-Za-z0-9]+)*"
_NAMED_BEFORE_KIND = re.compile(
    rf"\b(?P<name>{_NAME})(?=(?:\s+[A-Z]{{2,6}})?\s+"
    r"(?P<kind>dataset|benchmark|corpus|framework|method|model|algorithm)s?\b)"
)
_NAMED_AFTER_KIND = re.compile(
    rf"\b(?P<kind>(?i:dataset|benchmark|corpus|framework|method|model|algorithm))s?\s+"
    rf"(?:named|called)\s+(?P<name>{_NAME})\b",
)
_NAMED_APPOSITION = re.compile(
    rf"\b(?P<name>{_NAME})(?:\s*\([^)]{{1,24}}\))?,\s+"
    r"(?:an?\s+)?(?:novel\s+|new\s+)?"
    r"(?P<kind>(?i:dataset|benchmark|corpus|framework|method|model|algorithm))\b",
)
_PROPOSED_VIA = re.compile(
    r"\b(?i:propose|introduce|present)\s+"
    r"(?P<left>[A-Z][A-Za-z0-9-]*(?:\s+[A-Za-z][A-Za-z0-9-]*){0,4})\s+(?i:via)\s+"
    r"(?P<right>[A-Z][A-Za-z0-9-]*(?:\s+[A-Za-z][A-Za-z0-9-]*){0,4})"
    r"\s*\([A-Z][A-Z0-9-]{1,12}\)",
)


def _dynamic_mentions(text: str, gazetteer: Gazetteer) -> list[Mention]:
    """Find high-precision names introduced with an explicit dataset/method construction."""
    found: list[Mention] = []
    seen: set[tuple[int, int, str]] = set()

    def add(surface: str, start: int, kind: str) -> None:
        entity_type = "dataset" if kind.lower() in {"dataset", "benchmark", "corpus"} else "method"
        # Single title-cased adjectives/nouns ("Chinese corpus", "Existing methods") are
        # common sentence text, not scientific names. Require an internal capital, digit,
        # hyphen, or all-caps acronym for dynamically discovered one-token names.
        looks_named = (
            surface.isupper()
            or any(char.isupper() for char in surface[1:])
            or any(char.isdigit() for char in surface)
            or "-" in surface
        )
        if is_generic_surface(surface) or not looks_named:
            return
        end = start + len(surface)
        key = (start, end, entity_type)
        if key in seen:
            return
        seen.add(key)
        entity_id = gazetteer.resolve_surface(surface, entity_type)
        found.append(Mention(
            entity_id=entity_id or f"{entity_type}:{slugify(surface)}",
            entity_type=entity_type,
            canonical_name=(
                gazetteer.entries[entity_id].canonical_name if entity_id else surface
            ),
            surface=surface,
            start=start,
            end=end,
        ))

    for pattern in (_NAMED_BEFORE_KIND, _NAMED_AFTER_KIND, _NAMED_APPOSITION):
        for match in pattern.finditer(text):
            add(match.group("name"), match.start("name"), match.group("kind"))

    # Compositional proposed names such as "Foo Mixup via Optimal Transport (FMOT)"
    # describe two reusable techniques. Keep the exact left/right spans, not the acronym.
    for match in _PROPOSED_VIA.finditer(text):
        add(match.group("left"), match.start("left"), "method")
        add(match.group("right"), match.start("right"), "method")
    return found


def _make_edge(rel_type: str, from_id: str, to_id: str, paper: dict[str, Any],
               band: str, evidence: list[dict[str, Any]], extractor_version: str) -> dict[str, Any]:
    return {
        "type": rel_type, "from": from_id, "to": to_id,
        "extractor": EXTRACTOR, "extractor_version": extractor_version,
        "confidence_band": band,
        "evidence_paper_ids": [paper["id"]],
        "evidence": evidence[:MAX_EVIDENCE_PER_EDGE],
        "year": paper.get("year"),
    }


def extract_paper(paper: dict[str, Any], gazetteer: Gazetteer, extractor_version: str) -> dict[str, Any]:
    """Extract entities and relations from one paper's abstract. Pure function, no I/O."""
    paper_id = paper["id"]
    abstract = (paper.get("abstract") or "").strip()
    empty = {"paper_id": paper_id, "extractor": EXTRACTOR, "extractor_version": extractor_version,
             "entities": [], "edges": []}
    if not abstract:
        return empty

    sentences = split_sentences(abstract)
    mentions = gazetteer.match_text(abstract)
    claimed = {(mention.start, mention.end, mention.entity_type) for mention in mentions}
    for mention in _dynamic_mentions(abstract, gazetteer):
        key = (mention.start, mention.end, mention.entity_type)
        if key not in claimed:
            mentions.append(mention)
            claimed.add(key)
    mentions.sort(key=lambda mention: (mention.start, mention.end, mention.entity_type))
    if not mentions:
        return empty

    # Group mentions by entity and by sentence; record the evidence sentence for each.
    entity_mentions: dict[str, list[tuple[Mention, Sentence | None]]] = {}
    sentence_mentions: dict[int, list[Mention]] = {}
    for mention in mentions:
        sentence = sentence_at(sentences, mention.start)
        entity_mentions.setdefault(mention.entity_id, []).append((mention, sentence))
        if sentence is not None:
            sentence_mentions.setdefault(sentence.index, []).append(mention)

    entities = []
    for entity_id in sorted(entity_mentions):
        pairs = entity_mentions[entity_id]
        first_mention = pairs[0][0]
        evidence = []
        for mention, sentence in pairs[:MAX_EVIDENCE_PER_EDGE]:
            evidence.append({
                "paper_id": paper_id,
                "surface": mention.surface,
                "span_start": mention.start,
                "span_end": mention.end,
                "sentence_index": sentence.index if sentence else None,
                "evidence_text": sentence.text if sentence else "",
            })
        entities.append({
            "entity_id": entity_id, "entity_type": first_mention.entity_type,
            "canonical_name": first_mention.canonical_name, "resolved_by": "gazetteer",
            "n_mentions": len(pairs), "evidence": evidence,
        })

    edges = []
    # Paper-anchored edges: one per mentioned entity. Band depends on cue verbs in evidence.
    for entity_id in sorted(entity_mentions):
        pairs = entity_mentions[entity_id]
        entity_type = pairs[0][0].entity_type
        rel_type, cue_regex = _TYPE_TO_RELATION[entity_type]
        evidence = []
        band = "rule_medium"
        for mention, sentence in pairs:
            if sentence is None:
                continue
            evidence.append({"paper_id": paper_id, "surface": mention.surface,
                             "sentence_index": sentence.index, "evidence_text": sentence.text})
            if cue_regex.search(sentence.text):
                band = "rule_high"
        if evidence:
            edges.append(_make_edge(rel_type, paper_id, entity_id, paper, band, evidence, extractor_version))

    # Entity-to-entity: method evaluated on dataset, only with an evaluation cue in the sentence.
    for sentence_index in sorted(sentence_mentions):
        in_sentence = sentence_mentions[sentence_index]
        sentence = sentences[sentence_index]
        if not EVAL_CUES.search(sentence.text):
            continue
        methods = sorted({m.entity_id for m in in_sentence if m.entity_type == "method"})
        datasets = sorted({m.entity_id for m in in_sentence if m.entity_type == "dataset"})
        for method_id in methods:
            for dataset_id in datasets:
                evidence = [{"paper_id": paper_id, "surface": f"{method_id} / {dataset_id}",
                             "sentence_index": sentence_index, "evidence_text": sentence.text}]
                edges.append(_make_edge("METHOD_EVALUATED_ON", method_id, dataset_id, paper,
                                        "rule_high", evidence, extractor_version))
    return {"paper_id": paper_id, "extractor": EXTRACTOR, "extractor_version": extractor_version,
            "entities": entities, "edges": edges}
