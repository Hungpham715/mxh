import csv
import json

import pytest

from datasets.audit_dataset import build_manifest
from datasets.auto_review import validate_cases_against_graph
from datasets.build_independent_holdout import build_holdout
from datasets.build_sft import build_samples, parse_completion
from datasets.export_review import export_review, select_review_cases
from datasets.generate_from_graph import _unique_name_entities, generate
from datasets.generate_negative import build_negative_cases
from datasets.import_review import import_review
from datasets.io import write_models
from datasets.schema import QuestionCase, ReviewStatus
from datasets.split import assert_no_entity_leakage, assign_splits
from evaluation.run_eval import _label_level


@pytest.mark.asyncio
async def test_fake_generation_covers_all_query_templates() -> None:
    cases = await generate(provider="fake", seed=42, limit=20, execute=False)
    assert len(cases) == 19
    assert len({case.expected_query.intent for case in cases}) == 19
    assert all(case.review_status == ReviewStatus.NEEDS_REVIEW for case in cases)


@pytest.mark.asyncio
async def test_silver_validation_requeries_graph_and_matches_generated_facts() -> None:
    cases = await generate(provider="fake", seed=42, limit=12, execute=False)
    rows, stats = await validate_cases_against_graph(cases, provider="fake", execute=False)
    assert stats == {"yes": 12, "no": 0}
    assert all(row["reviewer_note"] == "silver_auto:graph_requery_exact_match" for row in rows)


def test_sampled_generation_excludes_duplicate_display_names() -> None:
    class Item:
        def __init__(self, item_id: str, name: str) -> None:
            self.id = item_id
            self.name = name

    unique = _unique_name_entities(
        [Item("a1", "Linh Nguyen"), Item("a2", "Linh Nguyen"), Item("a3", "An Nguyen")]
    )
    assert [item.id for item in unique] == ["a3"]


def test_negative_generation_is_explicitly_synthetic_and_verified() -> None:
    cases = build_negative_cases(42)
    assert len(cases) >= 6
    assert all(case.provenance["negative_is_candidate"] for case in cases)
    assert {case.expected_status for case in cases} >= {"not_found", "ambiguous", "out_of_scope"}


def test_split_keeps_shared_entities_together() -> None:
    cases = build_negative_cases(42)
    first = cases[0].model_copy(update={"group_id": "person-a"})
    second = cases[1].model_copy(
        update={
            "group_id": "person-a",
            "expected_query": cases[1].expected_query.model_copy(
                update={"entity_ids": first.expected_query.entity_ids}
            ),
        }
    )
    output = assign_splits([first, second, *cases[2:]], seed=42)
    assert_no_entity_leakage(output)
    selected = [case for case in output if case.group_id == "person-a"]
    assert len({case.split for case in selected}) == 1


def test_independent_holdout_removes_transitive_entity_component() -> None:
    cases = build_negative_cases(42)
    gold_query = cases[0].expected_query.model_copy(update={"entity_ids": ["entity:a"]})
    gold = cases[0].model_copy(
        update={
            "expected_query": gold_query,
            "group_id": "gold",
            "review_status": ReviewStatus.INDEPENDENT_APPROVED,
            "reviewer_note": "independent_codex:checked",
        }
    )
    first_query = cases[1].expected_query.model_copy(update={"entity_ids": ["entity:a", "entity:b"]})
    first = cases[1].model_copy(
        update={
            "expected_query": first_query,
            "group_id": "silver-1",
            "review_status": ReviewStatus.SILVER_APPROVED,
            "split": "train",
        }
    )
    second_query = cases[2].expected_query.model_copy(update={"entity_ids": ["entity:b"]})
    second = cases[2].model_copy(
        update={
            "expected_query": second_query,
            "group_id": "silver-2",
            "review_status": ReviewStatus.SILVER_APPROVED,
            "split": "val",
        }
    )
    safe_query = cases[3].expected_query.model_copy(update={"entity_ids": ["entity:safe"]})
    safe = cases[3].model_copy(
        update={
            "expected_query": safe_query,
            "group_id": "silver-safe",
            "review_status": ReviewStatus.SILVER_APPROVED,
            "split": "train",
        }
    )
    trainval, held_out, manifest = build_holdout([first, second, safe], [gold])
    assert [case.case_id for case in trainval] == [safe.case_id]
    assert held_out[0].split == "test"
    assert manifest["entity_and_group_leakage"] == "pass"


@pytest.mark.asyncio
async def test_review_csv_round_trip_approves_only_yes_rows(tmp_path) -> None:
    cases = await generate(provider="fake", seed=42, limit=2, execute=False)
    csv_path = tmp_path / "review.csv"
    export_review(cases, csv_path)
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
    rows[0]["label_valid"] = "yes"
    rows[0]["expected_answer"] = "Reviewed answer"
    rows[1]["label_valid"] = "unknown"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    accepted, rejected = import_review(cases, csv_path)
    assert rejected == []
    assert len(accepted) == 1
    assert accepted[0].review_status == ReviewStatus.APPROVED
    assert accepted[0].expected_facts.answer == "Reviewed answer"


@pytest.mark.asyncio
async def test_independent_review_stays_distinct_from_human_gold(tmp_path) -> None:
    cases = await generate(provider="fake", seed=42, limit=1, execute=False)
    csv_path = tmp_path / "review.csv"
    export_review(cases, csv_path)
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
    rows[0]["label_valid"] = "yes"
    rows[0]["reviewer_note"] = "independent_codex:source_checked"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    accepted, rejected = import_review(cases, csv_path, status_on_yes=ReviewStatus.INDEPENDENT_APPROVED)
    assert rejected == []
    assert accepted[0].review_status == ReviewStatus.INDEPENDENT_APPROVED
    held_out = [accepted[0].model_copy(update={"split": "test"})]
    assert _label_level(held_out, synthetic_smoke=False) == "nonhuman_source_review"


@pytest.mark.asyncio
async def test_auto_provenance_cannot_masquerade_as_human_gold(tmp_path) -> None:
    cases = await generate(provider="fake", seed=42, limit=1, execute=False)
    mislabeled = [
        cases[0].model_copy(
            update={
                "review_status": ReviewStatus.APPROVED,
                "reviewer_note": "auto:passed",
                "split": "test",
            }
        )
    ]
    with pytest.raises(ValueError, match="cannot be human gold"):
        _label_level(mislabeled, synthetic_smoke=False)
    input_path = tmp_path / "mislabeled.jsonl"
    write_models(input_path, mislabeled)
    manifest = build_manifest(mislabeled, input_path)
    assert manifest["human_gold_cases"] == 0
    assert manifest["invalid_human_provenance_cases"] == 1


@pytest.mark.asyncio
async def test_review_selection_is_reproducible_and_held_out() -> None:
    cases = await generate(provider="fake", seed=42, limit=20, execute=False)
    split_cases = [case.model_copy(update={"split": "test"}) for case in cases]
    first = select_review_cases(split_cases, split="test", limit=6, seed=7)
    second = select_review_cases(split_cases, split="test", limit=6, seed=7)
    assert [case.case_id for case in first] == [case.case_id for case in second]
    assert len(first) == 6
    assert all(case.split == "test" for case in first)


def test_build_sft_emits_parse_and_answer_messages() -> None:
    candidates = build_negative_cases(42)
    with pytest.raises(ValueError, match="no reviewed"):
        build_samples(candidates)
    fact = {
        "subject_id": "author:missing",
        "predicate": "WROTE",
        "object_id": "paper:x",
        "value": {"name": "X"},
    }
    approved_train = candidates[0].model_copy(
        update={
            "review_status": ReviewStatus.APPROVED,
            "split": "train",
            "expected_status": "answered",
            "expected_facts": candidates[0].expected_facts.model_copy(update={"answer": "X"}),
            "verified_facts": [fact],
        }
    )
    approved_test = candidates[1].model_copy(update={"review_status": ReviewStatus.APPROVED, "split": "test"})
    samples = build_samples([approved_train, approved_test])
    # The test-split case is excluded; the train case yields one PARSE and one ANSWER sample.
    assert len(samples) == 2
    assert {sample.task for sample in samples} == {"PARSE", "ANSWER"}
    assert all(sample.source_case_id == approved_train.case_id for sample in samples)
    for sample in samples:
        assert sample.messages[0]["role"] == "system"
        assert sample.messages[-1]["role"] == "assistant"


def test_parse_completion_satisfies_runtime_contract() -> None:
    """The gold PARSE assistant message must validate as a runtime QueryIntent (extra=forbid)."""
    from graphrag.models import QueryIntent

    for case in build_negative_cases(42):
        payload = json.loads(parse_completion(case))
        QueryIntent.model_validate(payload)


def test_question_case_json_schema_is_serializable() -> None:
    schema = QuestionCase.model_json_schema()
    json.dumps(schema)
    assert schema["title"] == "QuestionCase"


@pytest.mark.asyncio
async def test_dataset_audit_reports_action_coverage_without_inventing_gold(tmp_path) -> None:
    cases = await generate(provider="fake", seed=42, limit=20, execute=False)
    input_path = tmp_path / "cases.jsonl"
    write_models(input_path, cases)
    manifest = build_manifest(cases, input_path)
    assert manifest["quality_status"] == "pass"
    assert len(manifest["actions_present"]) == 19
    assert manifest["silver_cases"] == 0
    assert manifest["nonhuman_source_review_cases"] == 0
    assert manifest["human_gold_cases"] == 0
