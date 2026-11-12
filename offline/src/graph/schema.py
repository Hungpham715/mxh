"""Neo4j schema helpers (constraints) - thin re-export of the loader's schema functions."""
from src.graph.load import LABELS, ensure_schema

__all__ = ["LABELS", "ensure_schema"]
