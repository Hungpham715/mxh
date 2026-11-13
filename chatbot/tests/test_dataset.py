import csv
import json

import pytest

from datasets.build_sft import build_samples, parse_completion
from datasets.export_review import export_review
from datasets.generate_from_graph import generate
from datasets.generate_negative import build_negative_cases
from datasets.import_review import import_review
from datasets.schema import QuestionCase, ReviewStatus
from datasets.split import assert_no_entity_leakage, assign_splits


@pytest.mark.asyncio
async def test_fake_generation_covers_twelve_query_templates() -> None:
    cases = await generate(provider="fake", seed=42, limit=20, execute=False)
    assert len(cases) == 12
    assert len({case.expected_query.intent for case in cases}) == 12
    assert all(case.review_status == ReviewStatus.NEEDS_REVIEW for case in cases)


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


def test_build_sft_emits_parse_and_answer_messages() -> None:
    candidates = build_negative_cases(42)
    with pytest.raises(ValueError, match="no approved"):
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
