"""Tests for the enrichment pipeline: gazetteer matching, rule/LLM extraction, merge provenance."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.enrichment import extract_rules
from src.enrichment.audit import audit_enrichment
from src.enrichment.extract_llm import parse_and_validate
from src.enrichment.gazetteer import Gazetteer, slugify
from src.enrichment.merge import canonicalize, merge_all
from src.enrichment.textutil import sentence_at, split_sentences

MINI_GAZETTEER = """
gazetteer_version: test-v1
methods:
  - BERT
  - name: GPT
    aliases: [GPT, GPTs]
  - GPT-4
  - name: OPT
    case_sensitive: true
  - name: CNN
    aliases: [CNN, convolutional neural network]
datasets:
  - SQuAD
  - name: CNN/DailyMail
    aliases: [CNN/DailyMail, CNN-DM]
  - name: DROP
    case_sensitive: true
tasks:
  - name: Question Answering
    aliases: [question answering, QA]
"""


@pytest.fixture()
def gaz(tmp_path: Path) -> Gazetteer:
    path = tmp_path / "gazetteer.yaml"
    path.write_text(MINI_GAZETTEER, encoding="utf-8")
    return Gazetteer.from_file(path)


# ------------------------------------------------------------------ gazetteer
def test_slugify():
    assert slugify("GPT-3.5") == "gpt-3-5"
    assert slugify("CNN/DailyMail") == "cnn-dailymail"
    assert slugify("  Multi-Hop  Reasoning ") == "multi-hop-reasoning"


def test_longest_alias_wins(gaz: Gazetteer):
    mentions = gaz.match_text("GPT-4 beats GPT on many tasks")
    assert [(m.surface, m.entity_id) for m in mentions] == [
        ("GPT-4", "method:gpt-4"), ("GPT", "method:gpt")]


def test_case_sensitive_entries(gaz: Gazetteer):
    # lowercase common-word spellings must NOT match OPT / DROP
    assert gaz.match_text("the opt and the drop of water") == []
    mentions = gaz.match_text("OPT and DROP are used here")
    assert sorted(m.entity_id for m in mentions) == ["dataset:drop", "method:opt"]


def test_no_overlap_between_dataset_and_method(gaz: Gazetteer):
    mentions = gaz.match_text("summarization on the CNN/DailyMail dataset")
    entity_ids = [m.entity_id for m in mentions]
    assert "dataset:cnn-dailymail" in entity_ids
    assert "method:cnn" not in entity_ids  # span already claimed by the longer alias


def test_resolve_surface_requires_matching_type(gaz: Gazetteer):
    assert gaz.resolve_surface("BERT", "method") == "method:bert"
    assert gaz.resolve_surface("question answering", "task") == "task:question-answering"
    assert gaz.resolve_surface("BERT", "task") is None
    assert gaz.resolve_surface("XPhoneBERT", "method") is None


def test_real_gazetteer_loads():
    real = Gazetteer.from_file(Path(__file__).resolve().parents[1] / "configs" / "gazetteer.yaml")
    assert len(real.entries) > 150
    assert real.version == "gazetteer-v1.0"
    # a few sanity checks on curated content
    assert real.resolve_surface("LLaMA 2", "method") == "method:llama"
    assert real.resolve_surface("chain of thought", "method") == "method:chain-of-thought"
    assert real.resolve_surface("MS MARCO", "dataset") == "dataset:ms-marco"


# ------------------------------------------------------------------ textutil
def test_split_sentences_offsets():
    text = "First sentence. Second one! Third?"
    sentences = split_sentences(text)
    assert [s.text for s in sentences] == ["First sentence.", "Second one!", "Third?"]
    for s in sentences:
        assert text[s.start:s.end].strip() == s.text
    assert sentence_at(sentences, 0).index == 0
    assert sentence_at(sentences, 16).index == 1
    assert sentence_at(sentences, 999) is None


# ------------------------------------------------------------------ rules extractor
def _paper(abstract: str) -> dict:
    return {"id": "acl:test.1", "year": 2024, "abstract": abstract}


def test_rules_extract_paper_entities_and_edges(gaz: Gazetteer):
    result = extract_rules.extract_paper(
        _paper("We evaluate BERT on SQuAD for question answering. OPT is also discussed."),
        gaz, extractor_version="rules-test-v1")
    entity_ids = {e["entity_id"] for e in result["entities"]}
    assert entity_ids == {"method:bert", "dataset:squad", "task:question-answering", "method:opt"}

    edges = {(e["type"], e["from"], e["to"]): e for e in result["edges"]}
    assert ("USES_METHOD", "acl:test.1", "method:bert") in edges
    assert ("EVALUATED_ON", "acl:test.1", "dataset:squad") in edges
    assert ("ADDRESSES_TASK", "acl:test.1", "task:question-answering") in edges
    assert ("METHOD_EVALUATED_ON", "method:bert", "dataset:squad") in edges
    # OPT appears without an eval cue in its sentence -> no METHOD_EVALUATED_ON for it
    assert not any(k[2] == "method:opt" and k[0] == "METHOD_EVALUATED_ON" for k in edges)

    # confidence bands: "evaluate" is an eval cue (rule_high); plain mention is rule_medium
    assert edges[("EVALUATED_ON", "acl:test.1", "dataset:squad")]["confidence_band"] == "rule_high"
    assert edges[("USES_METHOD", "acl:test.1", "method:bert")]["confidence_band"] == "rule_medium"
    # every edge carries verbatim evidence text from the abstract
    for edge in result["edges"]:
        for item in edge["evidence"]:
            assert item["evidence_text"] in "We evaluate BERT on SQuAD for question answering. OPT is also discussed."


def test_rules_empty_abstract(gaz: Gazetteer):
    result = extract_rules.extract_paper(_paper(""), gaz, extractor_version="rules-test-v1")
    assert result["entities"] == [] and result["edges"] == []


# ------------------------------------------------------------------ llm parse/validate
ABSTRACT = "We evaluate BERT on SQuAD. BERT is great."


def test_parse_and_validate_keeps_grounded_items():
    content = json.dumps({
        "entities": [
            {"surface": "BERT", "type": "model"},        # synonym -> method
            {"surface": "SQuAD", "type": "benchmark"},   # synonym -> dataset
            {"surface": "GPT-9000", "type": "method"},   # hallucinated -> dropped
        ],
        "relations": [
            {"from_surface": "PAPER", "rel": "uses_method", "to_surface": "BERT",
             "evidence": "We evaluate BERT on SQuAD."},
            {"from_surface": "BERT", "rel": "method_evaluated_on", "to_surface": "SQuAD",
             "evidence": "We evaluate BERT on SQuAD."},
            {"from_surface": "PAPER", "rel": "evaluated_on", "to_surface": "made up thing",
             "evidence": "We evaluate BERT on SQuAD."},
        ],
    })
    entities, relations, drops, auto_added = parse_and_validate(content, ABSTRACT)
    assert [(e["surface"], e["type"]) for e in entities] == [("BERT", "method"), ("SQuAD", "dataset")]
    assert [(r["rel"], r["to_surface"]) for r in relations] == [
        ("USES_METHOD", "BERT"), ("METHOD_EVALUATED_ON", "SQuAD")]
    reasons = sorted(d["reason"] for d in drops)
    assert reasons == ["endpoint_not_extracted", "surface_not_in_abstract"]
    assert auto_added == []


def test_parse_rescues_missing_endpoint_from_abstract():
    # The 0.6b model often references a relation endpoint it forgot to list as an entity.
    content = json.dumps({
        "entities": [],
        "relations": [
            {"from_surface": "PAPER", "rel": "uses_method", "to_surface": "BERT",
             "evidence": "We evaluate BERT on SQuAD."},
            {"from_surface": "PAPER", "rel": "evaluated_on", "to_surface": "GhostBench",
             "evidence": "We evaluate BERT on SQuAD."},
        ],
    })
    entities, relations, drops, auto_added = parse_and_validate(content, ABSTRACT)
    assert [e["surface"] for e in entities] == ["BERT"]  # rescued, verbatim-grounded
    assert auto_added == ["BERT"]
    assert [(r["rel"], r["to_surface"]) for r in relations] == [("USES_METHOD", "BERT")]
    assert drops[0]["reason"] == "endpoint_not_extracted"  # GhostBench is not in the abstract


def test_parse_paper_entity_drop_and_evidence_fallback():
    content = json.dumps({
        "entities": [{"surface": "PAPER", "type": "method"},
                     {"surface": "BERT", "type": "method"}],
        "relations": [{"from_surface": "PAPER", "rel": "uses_method", "to_surface": "BERT",
                       "evidence": "A paraphrased sentence that is not verbatim."}],
    })
    entities, relations, drops, _auto = parse_and_validate(content, ABSTRACT)
    assert [e["surface"] for e in entities] == ["BERT"]
    assert drops[0]["reason"] == "invalid_entity"  # "PAPER" is an anchor, never an entity
    # paraphrased evidence falls back to the sentence containing the target surface
    assert relations[0]["evidence"]["evidence_source"] == "surface_sentence"
    assert relations[0]["evidence"]["evidence_text"] == "We evaluate BERT on SQuAD."


def test_parse_and_validate_grounded_evidence_fallback_and_rejects_bad_json():
    content = json.dumps({
        "entities": [{"surface": "BERT", "type": "method"}],
        "relations": [{"from_surface": "PAPER", "rel": "uses_method", "to_surface": "BERT",
                       "evidence": "This sentence is not in the abstract."}],
    })
    entities, relations, drops, _auto = parse_and_validate(content, ABSTRACT)
    assert entities
    assert len(relations) == 1
    assert relations[0]["evidence"] == {
        "sentence_index": 0,
        "evidence_text": "We evaluate BERT on SQuAD.",
        "evidence_source": "surface_sentence",
    }
    assert drops == []

    entities, relations, drops, _auto = parse_and_validate("not json at all", ABSTRACT)
    assert entities == [] and relations == [] and drops[0]["reason"] == "invalid_json"


# ------------------------------------------------------------------ merge
def test_merge_agreement_and_slug_resolution(gaz: Gazetteer):
    paper = _paper("We evaluate BERT on SQuAD. XPhoneBERT is a new model.")
    rules_result = extract_rules.extract_paper(paper, gaz, extractor_version="rules-test-v1")
    llm_result = {
        "paper_id": paper["id"], "extractor": "llm", "extractor_version": "test",
        "entities": [
            {"surface": "BERT", "type": "method",
             "evidence": {"sentence_index": 0, "evidence_text": "We evaluate BERT on SQuAD."}},
            {"surface": "XPhoneBERT", "type": "method",
             "evidence": {"sentence_index": 1, "evidence_text": "XPhoneBERT is a new model."}},
        ],
        "relations": [
            {"rel": "USES_METHOD", "from_surface": "PAPER", "to_surface": "BERT",
             "evidence": {"sentence_index": 0, "evidence_text": "We evaluate BERT on SQuAD."}},
        ],
        "drops": [],
    }
    entities, edges_by_type, stats = merge_all([paper], [rules_result], [llm_result], gaz)

    by_id = {e["id"]: e for e in entities}
    assert by_id["method:bert"]["resolved_by"] == "gazetteer"
    assert by_id["method:bert"]["extractors"] == ["llm", "rules"]  # seen by both extractors
    assert by_id["method:xphonebert"]["resolved_by"] == "slug"
    assert by_id["method:xphonebert"]["extractors"] == ["llm"]  # gazetteer cannot know it

    uses = {(e["from"], e["to"]): e for e in edges_by_type["USES_METHOD"]}
    bert_edge = uses[(paper["id"], "method:bert")]
    assert bert_edge["source_kind"] == "agreement"
    assert bert_edge["confidence_band"] == "agreement"
    assert bert_edge["extractors"] == ["llm", "rules"]
    assert bert_edge["evidence_paper_ids"] == [paper["id"]]

    opt_edge = uses.get((paper["id"], "method:xphonebert"))
    assert opt_edge is not None and opt_edge["source_kind"] == "llm"
    assert stats["edges_by_source_kind"]["agreement"] >= 1
    assert stats["llm"]["extractor_versions"] == {"test": 1}
    assert stats["llm"]["models"] == {"unknown": 1}


def test_merge_drops_endpoint_type_mismatch(gaz: Gazetteer):
    paper = _paper("BERT rocks.")
    llm_result = {
        "paper_id": paper["id"], "extractor": "llm", "extractor_version": "test",
        "entities": [{"surface": "BERT", "type": "method",
                      "evidence": {"sentence_index": 0, "evidence_text": "BERT rocks."}}],
        "relations": [{"rel": "EVALUATED_ON", "from_surface": "PAPER", "to_surface": "BERT",
                       "evidence": {"sentence_index": 0, "evidence_text": "BERT rocks."}}],
        "drops": [],
    }
    _entities, edges_by_type, stats = merge_all([paper], [], [llm_result], gaz)
    assert edges_by_type["EVALUATED_ON"] == []
    assert stats["llm"]["drop_reasons"]["endpoint_type_mismatch"] == 1


def test_merge_drops_generic_llm_surfaces(gaz: Gazetteer):
    paper = _paper("This paper proposes a model for the task.")
    llm_result = {
        "paper_id": paper["id"], "extractor": "llm", "extractor_version": "test",
        "entities": [
            {"surface": "paper", "type": "task",
             "evidence": {"sentence_index": 0, "evidence_text": "This paper proposes a model for the task."}},
            {"surface": "model", "type": "method",
             "evidence": {"sentence_index": 0, "evidence_text": "This paper proposes a model for the task."}},
        ],
        "relations": [], "drops": [],
    }
    entities, edges_by_type, stats = merge_all([paper], [], [llm_result], gaz)
    assert entities == []
    assert edges_by_type["USES_METHOD"] == []
    assert stats["llm"]["drop_reasons"]["generic_surface"] == 2


def test_canonicalize(gaz: Gazetteer):
    assert canonicalize("BERT", "method", gaz) == ("method:bert", "gazetteer")
    assert canonicalize("SomeUnknown Model", "method", gaz) == ("method:someunknown-model", "slug")


def test_nonhuman_audit_checks_verbatim_evidence_and_disclaims_semantic_metrics(tmp_path: Path):
    enriched = tmp_path / "enriched"
    processed = tmp_path / "processed"
    out = tmp_path / "audit"
    enriched.mkdir()
    processed.mkdir()
    (processed / "papers.jsonl").write_text(
        json.dumps({"id": "p1", "abstract": ABSTRACT}) + "\n", encoding="utf-8"
    )
    edge = {
        "type": "USES_METHOD", "from": "p1", "to": "method:bert", "source_kind": "agreement",
        "extractors": ["llm", "rules"], "confidence_band": "agreement",
        "verification_status": "unverified", "build_version": "test", "evidence_paper_ids": ["p1"],
        "evidence": [{"paper_id": "p1", "evidence_text": "We evaluate BERT on SQuAD."}],
    }
    (enriched / "edges_USES_METHOD.jsonl").write_text(json.dumps(edge) + "\n", encoding="utf-8")
    summary = audit_enrichment(enriched, processed, out, per_type=30)
    assert summary["audited_edges"] == 1 and summary["source_grounding_pass_rate"] == 1.0
    assert summary["provenance"]["human_review"] is False
    assert any("does not estimate semantic" in claim for claim in summary["claims_not_supported"])


def test_nonhuman_audit_accepts_bounded_evidence_subset(tmp_path: Path):
    enriched = tmp_path / "enriched"
    processed = tmp_path / "processed"
    out = tmp_path / "audit"
    enriched.mkdir()
    processed.mkdir()
    papers = [
        {"id": f"p{i}", "abstract": ABSTRACT}
        for i in range(1, 5)
    ]
    (processed / "papers.jsonl").write_text(
        "".join(json.dumps(paper) + "\n" for paper in papers), encoding="utf-8"
    )
    edge = {
        "type": "METHOD_EVALUATED_ON", "from": "method:bert", "to": "dataset:squad",
        "source_kind": "rules", "extractors": ["rules"], "confidence_band": "rule_high",
        "verification_status": "unverified", "build_version": "test",
        # All supporting papers are retained, but only three bounded evidence examples.
        "evidence_paper_ids": ["p1", "p2", "p3", "p4"],
        "evidence": [
            {"paper_id": f"p{i}", "evidence_text": "We evaluate BERT on SQuAD."}
            for i in range(1, 4)
        ],
    }
    (enriched / "edges_METHOD_EVALUATED_ON.jsonl").write_text(
        json.dumps(edge) + "\n", encoding="utf-8"
    )

    summary = audit_enrichment(enriched, processed, out, per_type=30)

    assert summary["audited_edges"] == 1
    assert summary["source_grounding_pass_rate"] == 1.0
