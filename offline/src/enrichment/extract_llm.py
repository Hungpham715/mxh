"""CPU-capable sub-1B LLM extractor via local Ollama.

This is the "small LLM (<= 9B parameters) used for data processing" component of the project:
the same local model that powers the chatbot also performs entity/relation extraction over
the 1,091 abstracts, complementing the deterministic gazetteer baseline in extract_rules.py.

Robustness rules (small models deviate, so every output is validated):
- Ollama is called with a JSON Schema, think=false, temperature=0, and CPU-only inference by
  default (``num_gpu=0``).
- Entity surfaces and relation evidence must be verbatim substrings of the abstract
  (whitespace-normalized, case-insensitive). Anything else is dropped and counted, never kept.
- Relation endpoints must refer to surfaces the model itself extracted in the same response.
- Each result is cached by paper + model + extractor version. Changing a prompt/model can
  therefore never silently reuse an incompatible old response.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import httpx

from src.common import log
from src.enrichment.schema import is_generic_surface
from src.enrichment.textutil import split_sentences, sentence_at

EXTRACTOR = "llm"
EXTRACTOR_VERSION = "sub1b-ollama-v2.1"
DEFAULT_MODEL = "qwen3.5:0.8b-q8_0"
DEFAULT_BASE_URL = "http://127.0.0.1:11434"

# NOTE: v1.0 carried a few-shot example; the 0.6b model copied example entities ("SQuAD",
# "PAPER") into abstracts that never mentioned them (29 surface_not_in_abstract drops in a
# 20-paper pilot). v1.1 is example-free: schema + hard verbatim rules only. The validation
# layer below still catches any leftover hallucination.
SYSTEM_PROMPT = """You extract a high-recall knowledge graph from ONE NLP research abstract.
You receive ONE abstract. Return ONLY valid JSON matching this schema:
{"entities":[{"surface":"...","type":"method|dataset|task"}],
 "relations":[{"from_surface":"...","rel":"uses_method|addresses_task|evaluated_on|method_evaluated_on","to_surface":"...","evidence":"..."}]}

Rules:
- Copy every "surface" and every "evidence" VERBATIM from the given abstract. Never invent text, never reuse text from these instructions.
- Extract EVERY explicit, relevant item, including compared baselines and newly proposed items.
- "method" includes a named model/algorithm/framework and a specific technical technique such as a decoding, training, augmentation, or optimization method.
- "dataset" includes a named dataset, benchmark, corpus, or evaluation set.
- "task" includes a specific research/application task the paper addresses; include explicit task phrases even when they are not proper names.
- Copy the SHORTEST complete name span: remove surrounding prose and entity-kind suffixes such as "dataset", "benchmark", "framework", "method", "model", or "algorithm". If a long name contains an explicit parenthesized acronym, use the acronym as the surface.
- A dataset must be a named reusable data/evaluation resource. Languages, people, software tools, and generic phrases such as "public datasets" are not datasets.
- A method must be a reusable technical method. Do not label task names, error categories, pipeline stages, generic roles such as "teacher model"/"target model", or broad phrases such as "foundation models" as methods.
- A task must be a research objective evaluated or claimed by this paper. Do not label a language list, a data field, a stage name, a number of questions, or generic components such as retrieval/reasoning/composition unless the paper explicitly evaluates that component as a task.
- Do NOT extract generic words such as model, method, paper, data, parameters, system, approach, results, performance. Only proper names or established technical terms.
- Never output the literal word "PAPER". The paper subject is implicit and added by code.
- The "entities" list MUST contain every surface you reference in "relations".
- For uses_method / addresses_task / evaluated_on the subject is implicit: set from_surface to an empty string and to_surface to the entity surface.
- Emit one paper relation for every entity genuinely used, addressed, introduced, or evaluated by this paper. Do not link background-only mentions.
- method_evaluated_on connects a method surface (from_surface) to a dataset surface (to_surface) when the abstract says the method was evaluated/tested/benchmarked on that dataset.
- "evidence" must be exactly one sentence copied from the abstract that supports the relation.
- Re-read the whole abstract once for missed methods, datasets, and tasks before returning. Empty lists are valid only when none are explicit."""

EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "surface": {"type": "string"},
                    "type": {"type": "string", "enum": ["method", "dataset", "task"]},
                },
                "required": ["surface", "type"],
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "from_surface": {"type": "string"},
                    "rel": {
                        "type": "string",
                        "enum": [
                            "uses_method",
                            "addresses_task",
                            "evaluated_on",
                            "method_evaluated_on",
                        ],
                    },
                    "to_surface": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["from_surface", "rel", "to_surface", "evidence"],
            },
        },
    },
    "required": ["entities", "relations"],
}

# The 0.6b model does not follow the type enum perfectly (observed: "model", "benchmark").
# Map known synonyms; unknown types are dropped and counted.
_TYPE_MAP = {
    "method": "method", "model": "method", "approach": "method", "technique": "method",
    "architecture": "method", "framework": "method", "algorithm": "method",
    "dataset": "dataset", "benchmark": "dataset", "corpus": "dataset", "data": "dataset",
    "evaluation_set": "dataset", "evaluationset": "dataset",
    "task": "task", "application": "task", "problem": "task",
}
_REL_MAP = {
    "uses_method": "USES_METHOD", "use_method": "USES_METHOD", "uses": "USES_METHOD",
    "addresses_task": "ADDRESSES_TASK", "address_task": "ADDRESSES_TASK", "addresses": "ADDRESSES_TASK",
    "evaluated_on": "EVALUATED_ON", "evaluates_on": "EVALUATED_ON", "evaluate_on": "EVALUATED_ON",
    "method_evaluated_on": "METHOD_EVALUATED_ON",
    "method_evaluated_on_dataset": "METHOD_EVALUATED_ON",
}
# For paper-anchored relations, the relation type determines the entity type of the target.
# Used to rescue endpoints the model referenced in relations but forgot to list as entities.
_INFERRED_TARGET_TYPE = {"USES_METHOD": "method", "EVALUATED_ON": "dataset", "ADDRESSES_TASK": "task"}


def _normalize(text: str) -> str:
    """Whitespace-normalized lowercase form, used only for substring verification."""
    return re.sub(r"\s+", " ", text).strip().lower()


def _clean_key(value: str) -> str:
    return re.sub(r"[\s-]+", "_", str(value).strip().lower())


def _cache_path(cache_dir: Path, paper_id: str, model: str = DEFAULT_MODEL) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", paper_id)
    model_key = re.sub(r"[^A-Za-z0-9._-]", "_", model)
    version_key = re.sub(r"[^A-Za-z0-9._-]", "_", EXTRACTOR_VERSION)
    return cache_dir / model_key / version_key / f"{safe}.json"


def call_ollama(base_url: str, model: str, abstract: str, timeout_seconds: float = 180.0,
                temperature: float = 0.0, num_predict: int = 768,
                num_gpu: int = 0) -> dict[str, Any]:
    """One synchronous chat completion. Returns the parsed Ollama response dict.

    temperature > 0 is used on retries: greedy decoding is deterministic, so retrying a
    degenerate/truncated generation at temperature 0 would reproduce the exact same failure.
    """
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Abstract:\n{abstract}\n\nExtract JSON."},
        ],
        "stream": False,
        "think": False,
        "format": EXTRACTION_SCHEMA,
        # The old 320-token ceiling was enough for precision-first output but can truncate the
        # longer candidate lists needed for recall. 768 stays bounded for a sub-1B CPU model.
        # The longest abstract in this frozen 1,091-paper snapshot is 1,917 characters;
        # 2,048 tokens comfortably covers prompt + abstract + bounded response. Keeping this
        # explicit also allows six parallel CPU slots within less context memory than 4x4,096.
        "options": {
            "temperature": temperature,
            "num_predict": num_predict,
            "num_ctx": 4096,
            "num_gpu": num_gpu,
        },
    }
    response = httpx.post(f"{base_url.rstrip('/')}/api/chat", json=payload, timeout=timeout_seconds)
    response.raise_for_status()
    return response.json()


def parse_and_validate(content: str, abstract: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Validate one raw LLM response against the abstract.

    Returns (entities, relations, drops, auto_added_surfaces).
    Every kept item cites verbatim abstract text; every rejected item lands in drops with a
    machine-readable reason (audit trail). The 0.6b model often references a relation endpoint
    it forgot to list under "entities"; when that surface is verbatim in the abstract it is
    auto-added as an entity (type inferred from the relation) and counted in auto_added_surfaces.
    """
    drops: list[dict[str, Any]] = []
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        return [], [], [{"reason": "invalid_json", "detail": str(exc)}], []
    if not isinstance(data, dict):
        return [], [], [{"reason": "invalid_json", "detail": "top level is not an object"}], []

    abstract_norm = _normalize(abstract)
    sentences = split_sentences(abstract)

    def locate(surface: str) -> int:
        """Offset of the surface in the abstract (case/whitespace-insensitive), -1 if absent."""
        needle = _normalize(surface)
        if not needle:
            return -1
        return abstract_norm.find(needle)

    def evidence_for(offset: int, fallback: str) -> dict[str, Any]:
        sentence = sentence_at(sentences, offset)
        if sentence is None:
            return {"sentence_index": None, "evidence_text": fallback}
        return {"sentence_index": sentence.index, "evidence_text": sentence.text}

    entities: list[dict[str, Any]] = []
    seen_surfaces: dict[str, str] = {}  # normalized surface -> entity type
    for raw in data.get("entities") or []:
        if not isinstance(raw, dict):
            drops.append({"reason": "malformed_entity", "detail": repr(raw)[:80]})
            continue
        surface = str(raw.get("surface") or "").strip()
        raw_type = _clean_key(str(raw.get("type") or ""))
        entity_type = _TYPE_MAP.get(raw_type)
        if not surface:
            drops.append({"reason": "empty_surface"})
            continue
        if surface.upper() == "PAPER":
            # Observed failure: the model echoes the relation anchor as an entity.
            drops.append({"reason": "invalid_entity", "surface": surface})
            continue
        if entity_type is None:
            drops.append({"reason": "unknown_type", "detail": raw_type, "surface": surface})
            continue
        offset = locate(surface)
        if offset < 0:
            # Hallucination guard: the model must copy from the abstract, not invent names.
            drops.append({"reason": "surface_not_in_abstract", "surface": surface})
            continue
        key = _normalize(surface)
        if key in seen_surfaces:
            continue
        seen_surfaces[key] = entity_type
        entities.append({"surface": surface, "type": entity_type,
                         "evidence": evidence_for(offset, surface)})

    relations: list[dict[str, Any]] = []
    auto_added: list[str] = []

    def rescue_endpoint(surface: str, inferred_type: str) -> bool:
        """Ensure a relation endpoint exists as an entity, adding it when grounded in the abstract.

        Returns True when the surface is a known entity afterwards. The added entity still goes
        through the generic-surface filter in merge.py, so junk like "dataset" or "AL" is dropped.
        """
        key = _normalize(surface)
        if not key:
            return False
        if key in seen_surfaces:
            return True
        if is_generic_surface(surface):
            return False  # rescued junk ("dataset", "AL", ...) never becomes an entity
        offset = locate(surface)
        if offset < 0:
            return False
        seen_surfaces[key] = inferred_type
        entities.append({"surface": surface, "type": inferred_type,
                         "evidence": evidence_for(offset, surface)})
        auto_added.append(surface)
        return True

    for raw in data.get("relations") or []:
        if not isinstance(raw, dict):
            drops.append({"reason": "malformed_relation", "detail": repr(raw)[:80]})
            continue
        rel_type = _REL_MAP.get(_clean_key(str(raw.get("rel") or "")))
        from_surface = str(raw.get("from_surface") or "").strip()
        to_surface = str(raw.get("to_surface") or "").strip()
        evidence = str(raw.get("evidence") or "").strip()
        if rel_type is None:
            drops.append({"reason": "unknown_rel", "detail": str(raw.get("rel"))[:40]})
            continue
        if to_surface.upper() == "PAPER":
            # Observed failure: the model echoes the "PAPER" anchor as the target. Not a relation.
            drops.append({"reason": "invalid_endpoint", "rel": rel_type, "detail": "target is PAPER"})
            continue
        if rel_type == "METHOD_EVALUATED_ON":
            if not rescue_endpoint(from_surface, "method") or not rescue_endpoint(to_surface, "dataset"):
                drops.append({"reason": "endpoint_not_extracted", "from": from_surface, "to": to_surface})
                continue
            if seen_surfaces[_normalize(from_surface)] != "method" or seen_surfaces[_normalize(to_surface)] != "dataset":
                drops.append({"reason": "endpoint_type_mismatch", "from": from_surface, "to": to_surface})
                continue
        else:
            # The prompt asks for "PAPER" as the subject anchor; tolerate the entity itself.
            from_surface = "PAPER"
            inferred_type = _INFERRED_TARGET_TYPE[rel_type]
            if not rescue_endpoint(to_surface, inferred_type):
                drops.append({"reason": "endpoint_not_extracted", "to": to_surface})
                continue
            if seen_surfaces[_normalize(to_surface)] != inferred_type:
                drops.append({"reason": "endpoint_type_mismatch", "to": to_surface})
                continue
        evidence_offset = locate(evidence)
        evidence_source = "llm_verbatim"
        if not evidence or evidence_offset < 0:
            # The 0.6b model often mangles long copied sentences. Fall back to the sentence
            # containing the relation's target surface — still grounded verbatim in the abstract.
            evidence_offset = locate(to_surface)
            if evidence_offset < 0:
                drops.append({"reason": "evidence_not_in_abstract", "rel": rel_type, "detail": evidence[:60]})
                continue
            evidence_source = "surface_sentence"
        evidence_record = evidence_for(evidence_offset, evidence or to_surface)
        evidence_record["evidence_source"] = evidence_source
        relations.append({"rel": rel_type, "from_surface": from_surface, "to_surface": to_surface,
                          "evidence": evidence_record})
    return entities, relations, drops, auto_added


def extract_paper_llm(paper: dict[str, Any], cache_dir: Path, base_url: str = DEFAULT_BASE_URL,
                      model: str = DEFAULT_MODEL, max_attempts: int = 3,
                      num_gpu: int = 0) -> dict[str, Any]:
    """Extract one paper, using the on-disk cache when present (resume-friendly).

    Failures are NOT cached, so a re-run retries them. The returned record carries
    "error" instead of entities/relations when all attempts failed.
    """
    paper_id = paper["id"]
    path = _cache_path(cache_dir, paper_id, model)
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    abstract = (paper.get("abstract") or "").strip()
    if not abstract:
        record: dict[str, Any] = {"paper_id": paper_id, "extractor": EXTRACTOR,
                                  "extractor_version": EXTRACTOR_VERSION, "model": model,
                                  "entities": [], "relations": [], "drops": [],
                                  "skipped": "empty_abstract"}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        return record

    last_error = ""
    for attempt in range(1, max_attempts + 1):
        try:
            started = time.perf_counter()
            retry_temperature = 0.0 if attempt == 1 else 0.3
            response = call_ollama(
                base_url,
                model,
                abstract,
                temperature=retry_temperature,
                num_predict=768 if attempt == 1 else 1024,
                num_gpu=num_gpu,
            )
            duration_ms = int((time.perf_counter() - started) * 1000)
            content = str(response.get("message", {}).get("content") or "")
            entities, relations, drops, auto_added = parse_and_validate(content, abstract)
            if not entities and not relations and any(d["reason"] == "invalid_json" for d in drops):
                last_error = "invalid_json"
                continue  # retry generation once more before giving up
            record = {"paper_id": paper_id, "extractor": EXTRACTOR,
                      "extractor_version": EXTRACTOR_VERSION, "model": model,
                      "entities": entities, "relations": relations, "drops": drops,
                      "auto_added_endpoints": auto_added,
                      "duration_ms": duration_ms,
                      "eval_count": response.get("eval_count"),
                      "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
            return record
        except (httpx.HTTPError, json.JSONDecodeError, OSError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            log.warning("llm extract %s attempt %d failed: %s", paper_id, attempt, last_error[:120])
            time.sleep(2 * attempt)
    return {"paper_id": paper_id, "extractor": EXTRACTOR, "extractor_version": EXTRACTOR_VERSION,
            "model": model, "error": last_error}
