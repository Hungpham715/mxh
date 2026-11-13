import json

import pytest

from training.train_sft import load_config, validate_dataset


def test_training_config_and_empty_dry_run_are_valid() -> None:
    config = load_config(__import__("pathlib").Path("training/config_sft.yaml"))
    assert config["model_id"] == "Qwen/Qwen3-0.6B"
    assert config["assistant_only_loss"] is True
    assert config["completion_only_loss"] is False
    assert validate_dataset(None) == {"train": 0, "val": 0}


def _sample(sample_id: str, split: str, task: str = "PARSE") -> dict:
    return {
        "sample_id": sample_id,
        "task": task,
        "split": split,
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "QUESTION:\nx"},
            {"role": "assistant", "content": "{}"},
        ],
    }


def test_training_data_rejects_test_split(tmp_path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps(_sample("x", "test")) + "\n")
    with pytest.raises(ValueError, match="test is forbidden"):
        validate_dataset(path)


def test_validate_dataset_counts_train_and_val(tmp_path) -> None:
    path = tmp_path / "ok.jsonl"
    rows = [_sample("a", "train"), _sample("b", "val", "ANSWER")]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    assert validate_dataset(path) == {"train": 1, "val": 1}


def test_validate_dataset_requires_assistant_last(tmp_path) -> None:
    path = tmp_path / "bad_order.jsonl"
    row = _sample("a", "train")
    row["messages"] = [row["messages"][0], row["messages"][2], row["messages"][1]]
    path.write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="assistant turn"):
        validate_dataset(path)


def test_notebooks_are_valid_json() -> None:
    from pathlib import Path

    for path in [
        Path("training/notebooks/qwen3_06b_sft_colab.ipynb"),
        Path("datasets/notebooks/prepare_and_review_dataset.ipynb"),
    ]:
        notebook = json.loads(path.read_text(encoding="utf-8"))
        assert notebook["nbformat"] == 4
        assert any(cell["cell_type"] == "code" for cell in notebook["cells"])
