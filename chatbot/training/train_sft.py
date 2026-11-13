"""Shared dry-run and explicitly gated Qwen3 LoRA training entrypoint."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import yaml

REQUIRED_CONFIG = {
    "model_id",
    "output_dir",
    "seed",
    "max_length",
    "learning_rate",
    "num_train_epochs",
    "per_device_train_batch_size",
    "gradient_accumulation_steps",
    "lora",
}

REQUIRED_SAMPLE_FIELDS = {"sample_id", "messages", "split", "task"}
VALID_ROLES = {"system", "user", "assistant"}


def load_config(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("training config must be a YAML object")
    missing = REQUIRED_CONFIG - data.keys()
    if missing:
        raise ValueError(f"training config is missing: {sorted(missing)}")
    if int(data["max_length"]) > 2048:
        raise ValueError("max_length above 2048 is not approved for this setup")
    lora = data["lora"]
    if lora.get("r") not in {8, 16}:
        raise ValueError("LoRA r must start at 8 or 16")
    return data


def _validate_messages(messages: Any, location: str) -> None:
    if not isinstance(messages, list) or not messages:
        raise ValueError(f"{location}: messages must be a non-empty list")
    roles = []
    for turn in messages:
        if not isinstance(turn, dict) or "role" not in turn or "content" not in turn:
            raise ValueError(f"{location}: every message needs role and content")
        if turn["role"] not in VALID_ROLES:
            raise ValueError(f"{location}: invalid role {turn['role']!r}")
        if not isinstance(turn["content"], str):
            raise ValueError(f"{location}: message content must be a string")
        roles.append(turn["role"])
    if roles[-1] != "assistant":
        raise ValueError(f"{location}: last message must be the assistant turn")


def validate_dataset(path: Path | None) -> dict[str, int]:
    if path is None:
        return {"train": 0, "val": 0}
    counts = {"train": 0, "val": 0}
    seen_ids: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            try:
                row = json.loads(raw_line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{line_number}: invalid JSON") from error
            missing = REQUIRED_SAMPLE_FIELDS - row.keys()
            if missing:
                raise ValueError(f"{path}:{line_number}: missing SFT fields {sorted(missing)}")
            if row["sample_id"] in seen_ids:
                raise ValueError(f"duplicate sample_id: {row['sample_id']}")
            seen_ids.add(row["sample_id"])
            if row["split"] not in counts:
                raise ValueError("SFT data may contain train/val only; test is forbidden")
            _validate_messages(row["messages"], f"{path}:{line_number}")
            counts[row["split"]] += 1
    return counts


def cuda_status() -> dict[str, Any]:
    try:
        import torch
    except ImportError:
        return {"torch_installed": False, "cuda_available": False}
    status = {"torch_installed": True, "cuda_available": torch.cuda.is_available()}
    if torch.cuda.is_available():
        properties = torch.cuda.get_device_properties(0)
        status.update(
            {
                "device": properties.name,
                "vram_gib": round(properties.total_memory / (1024**3), 2),
            }
        )
    return status


def run_training(config: dict[str, Any], dataset_path: Path, resume: str | None) -> None:
    if os.environ.get("ALLOW_MXH_SFT_TRAINING") != "1":
        raise RuntimeError("set ALLOW_MXH_SFT_TRAINING=1 to confirm an approved GPU training run")
    status = cuda_status()
    if not status.get("cuda_available"):
        raise RuntimeError("CUDA is unavailable; use the Colab notebook or another approved GPU")

    try:
        from peft import LoraConfig
        from trl import SFTConfig, SFTTrainer

        from datasets import load_dataset
    except ImportError as error:
        raise RuntimeError("install training dependencies with `uv sync --extra hf`") from error

    raw = load_dataset("json", data_files=str(dataset_path), split="train")
    train_dataset = raw.filter(lambda row: row["split"] == "train").select_columns(["messages"])
    eval_dataset = raw.filter(lambda row: row["split"] == "val").select_columns(["messages"])
    if len(train_dataset) == 0 or len(eval_dataset) == 0:
        raise ValueError("training requires non-empty reviewed train and validation splits")

    lora = config["lora"]
    peft_config = LoraConfig(
        r=int(lora["r"]),
        lora_alpha=int(lora["alpha"]),
        lora_dropout=float(lora["dropout"]),
        target_modules=list(lora["target_modules"]),
        task_type="CAUSAL_LM",
    )
    training_args = SFTConfig(
        output_dir=config["output_dir"],
        seed=int(config["seed"]),
        max_length=int(config["max_length"]),
        learning_rate=float(config["learning_rate"]),
        num_train_epochs=float(config["num_train_epochs"]),
        per_device_train_batch_size=int(config["per_device_train_batch_size"]),
        per_device_eval_batch_size=int(config["per_device_eval_batch_size"]),
        gradient_accumulation_steps=int(config["gradient_accumulation_steps"]),
        eval_strategy=config.get("eval_strategy", "epoch"),
        save_strategy=config.get("save_strategy", "epoch"),
        logging_steps=int(config.get("logging_steps", 10)),
        gradient_checkpointing=bool(config.get("gradient_checkpointing", True)),
        bf16=bool(config.get("bf16", True)),
        fp16=bool(config.get("fp16", False)),
        assistant_only_loss=bool(config.get("assistant_only_loss", True)),
        completion_only_loss=bool(config.get("completion_only_loss", False)),
        report_to="none",
        load_best_model_at_end=False,
    )
    trainer = SFTTrainer(
        model=config["model_id"],
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        peft_config=peft_config,
    )
    trainer.train(resume_from_checkpoint=resume)
    trainer.save_model(config["output_dir"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("training/config_sft.yaml"))
    parser.add_argument("--dataset", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--train", action="store_true")
    parser.add_argument("--resume")
    args = parser.parse_args()
    config = load_config(args.config)
    counts = validate_dataset(args.dataset)
    status = cuda_status()
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "DRY_RUN_ONLY",
                    "config_valid": True,
                    "dataset_counts": counts,
                    "cuda": status,
                    "model_weights_loaded": False,
                    "optimizer_created": False,
                },
                indent=2,
            )
        )
        return
    if args.dataset is None:
        raise SystemExit("--train requires --dataset with reviewed train/val SFT samples")
    run_training(config, args.dataset, args.resume)


if __name__ == "__main__":
    main()
