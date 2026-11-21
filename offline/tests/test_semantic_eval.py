import json
from pathlib import Path

from src.enrichment.semantic_eval import evaluate_semantic


def test_semantic_eval_scores_exact_ids_and_detects_misses(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "entities.jsonl").write_text(
        json.dumps({
            "id": "method:bert",
            "entity_type": "method",
            "evidence_paper_ids": ["p1"],
            # This bounded preview deliberately points elsewhere: complete membership wins.
            "evidence": [{"paper_id": "preview-only"}],
        }) + "\n",
        encoding="utf-8",
    )
    (data / "edges_USES_METHOD.jsonl").write_text(
        json.dumps({"type": "USES_METHOD", "from": "p1", "to": "method:bert", "evidence_paper_ids": ["p1"]}) + "\n",
        encoding="utf-8",
    )
    processed = tmp_path / "processed"
    processed.mkdir()
    abstract = "We use BERT."
    (processed / "papers.jsonl").write_text(json.dumps({"id": "p1", "abstract": abstract}) + "\n", encoding="utf-8")
    gold = tmp_path / "gold.jsonl"
    import hashlib
    gold.write_text(json.dumps({
        "paper_id": "p1",
        "abstract_sha256": hashlib.sha256(abstract.encode()).hexdigest(),
        "entities": [{"id": "method:bert", "type": "method"}, {"id": "task:qa", "type": "task"}],
        "relations": [
            {"type": "USES_METHOD", "from": "p1", "to": "method:bert"},
            {"type": "ADDRESSES_TASK", "from": "p1", "to": "task:qa"},
        ],
    }) + "\n", encoding="utf-8")
    result = evaluate_semantic(data, processed, gold, tmp_path / "scores.json")
    assert result["entity"]["micro"]["tp"] == 1
    assert result["entity"]["micro"]["fn"] == 1
    assert result["relation"]["micro"]["tp"] == 1
    assert result["relation"]["micro"]["fn"] == 1
    assert result["entity"]["bootstrap_95_ci"]["unit"] == "paper"
    assert result["entity"]["bootstrap_95_ci"]["replicates"] == 10_000
    assert result["entity"]["bootstrap_95_ci"]["f1"] == [0.6667, 0.6667]
