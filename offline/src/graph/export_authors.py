"""Export the Author-only projection (canonical pairs) from local derived edges or from Neo4j."""
from __future__ import annotations

from pathlib import Path

from src.analysis.metrics import build_projection, write_pairs_csv
from src.common import OUTPUT, PROCESSED
from src.data.contracts import load_dataset
from src.graph.derive import derive_edges


def export_author_projection(data_dir: Path = PROCESSED, out: Path = OUTPUT / "analysis" / "author_projection_edges.csv") -> int:
    rows = load_dataset(data_dir)
    g = build_projection(rows["authors.jsonl"], derive_edges(rows)["COAUTHORED_WITH"])
    write_pairs_csv(g, out)
    return g.number_of_edges()
