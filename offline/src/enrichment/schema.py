"""Shared constants and record shapes for the enrichment pipeline.

The enrichment graph lives in its OWN Neo4j scope (nlpgraph-enrich-v1). It references the
existing v1 Paper nodes by id but never modifies them, so the stabilized v1 graph and the
chatbot benchmarks are unaffected.
"""
from __future__ import annotations

from src.enrichment.gazetteer import slugify

ENRICH_SCOPE_ID = "nlpgraph-enrich-v1"
ENRICH_VERSION = "enrich-1.0.0"

# Relationship type -> (from label, to label). Paper-anchored edges carry the text evidence;
# METHOD_EVALUATED_ON is the only entity-to-entity type (e.g. BERT -> SQuAD).
ENRICH_REL_SCHEMA: dict[str, tuple[str, str]] = {
    "USES_METHOD": ("Paper", "Method"),
    "ADDRESSES_TASK": ("Paper", "Task"),
    "EVALUATED_ON": ("Paper", "Dataset"),
    "METHOD_EVALUATED_ON": ("Method", "Dataset"),
}
ENRICH_REL_TYPES = tuple(ENRICH_REL_SCHEMA)

ENTITY_TYPE_TO_LABEL = {"method": "Method", "dataset": "Dataset", "task": "Task"}

# Confidence bands, strongest first. "agreement" means both independent extractors
# (rules and LLM) produced the same edge; it is the band we trust most without human review.
CONFIDENCE_ORDER = ("agreement", "rule_high", "llm_extracted", "rule_medium")

MAX_EVIDENCE_PER_EDGE = 3


def best_band(bands: list[str]) -> str:
    """Return the strongest confidence band from a list (unknown bands rank lowest)."""
    ranked = [b for b in CONFIDENCE_ORDER if b in bands]
    if ranked:
        return ranked[0]
    return "rule_medium"


# Generic nouns the small LLM tends to emit as "entities" (observed in pilots: "paper",
# "model", "task", "dataset", ...). Applied ONLY to slug-resolved surfaces — gazetteer hits
# are curated and exempt — compared in slug form. Shared by parse-time rescue (extract_llm)
# and merge-time filtering (merge.py).
GENERIC_SLUGS = {
    "paper", "papers", "model", "models", "method", "methods", "approach", "approaches",
    "technique", "techniques", "algorithm", "algorithms", "framework", "frameworks",
    "system", "systems", "data", "dataset", "datasets", "benchmark", "benchmarks",
    "corpus", "task", "tasks", "parameter", "parameters", "cost", "result", "results",
    "performance", "quality", "analysis", "evaluation", "experiment", "experiments",
    "language", "languages", "text", "texts", "information", "knowledge", "open-source",
    "computational", "natural-language", "machine", "learning", "deep-learning",
    "neural-network", "neural-networks", "llm", "llms", "abstract", "study", "work",
    "problem", "problems", "application", "applications", "baseline", "baselines",
    "state-of-the-art", "training", "inference", "context", "query", "queries",
    "document", "documents", "sentence", "sentences", "word", "words", "the",
    "natural-language-understanding-nlu", "parallel-corpora", "recommender-system",
}


def is_generic_surface(surface: str) -> bool:
    """True when a surface is a generic noun (or too short to be a meaningful entity name)."""
    slug = slugify(surface)
    return len(slug) < 3 or slug in GENERIC_SLUGS
