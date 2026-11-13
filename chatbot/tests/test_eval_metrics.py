import json
from argparse import Namespace

import pytest

from datasets.generate_from_graph import generate
from datasets.io import write_models
from evaluation.compare import compare
from evaluation.metrics import percentile, precision_recall_f1, token_f1
from evaluation.run_eval import evaluate, write_report


def test_metric_formulas() -> None:
    score = precision_recall_f1({"a", "b"}, {"b", "c"})
    assert score == {"precision": 0.5, "recall": 0.5, "f1": 0.5}
    assert token_f1("Graph evidence", "graph evidence") == 1.0
    assert percentile([1, 2, 3, 4, 5], 0.95) == 5


@pytest.mark.asyncio
async def test_synthetic_eval_runs_real_pipeline_and_writes_banner(tmp_path) -> None:
    cases = await generate(provider="fake", seed=42, limit=4, execute=False)
    dataset = tmp_path / "synthetic.jsonl"
    write_models(dataset, cases)
    args = Namespace(
        dataset=dataset,
        synthetic_smoke=True,
        provider="fake",
        graph="fake",
        max_iterations=5,
        seed=42,
    )
    summary, rows = await evaluate(args)
    assert summary["synthetic_smoke_only"] is True
    assert summary["metrics"]["cases"] == 4
    assert len(rows) == 4
    output_dir = tmp_path / "report"
    write_report(output_dir, summary, rows)
    assert "SYNTHETIC SMOKE ONLY" in (output_dir / "summary.md").read_text()


def test_compare_marks_absent_b2_not_run(tmp_path) -> None:
    base = {
        "synthetic_smoke_only": False,
        "dataset_sha256": "same",
        "metrics": {"query_template_accuracy": 0.5, "answer_token_f1": 0.4},
    }
    b0 = tmp_path / "b0.json"
    b1 = tmp_path / "b1.json"
    b0.write_text(json.dumps(base))
    b1.write_text(json.dumps(base))
    result = compare(b0, b1, None)
    assert result["B2_sft_iterative"] == "not_run"


def test_compare_rejects_mixed_datasets(tmp_path) -> None:
    b0 = tmp_path / "b0.json"
    b1 = tmp_path / "b1.json"
    b0.write_text(json.dumps({"synthetic_smoke_only": False, "dataset_sha256": "a", "metrics": {}}))
    b1.write_text(json.dumps({"synthetic_smoke_only": False, "dataset_sha256": "b", "metrics": {}}))
    with pytest.raises(ValueError, match="same held-out dataset"):
        compare(b0, b1, None)
