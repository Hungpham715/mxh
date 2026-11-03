"""Small-world comparison on the author-only LCC (kept as its own module per architecture.md)."""
from src.analysis.metrics import avg_shortest_path, small_world

__all__ = ["small_world", "avg_shortest_path"]
