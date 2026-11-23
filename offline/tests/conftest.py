"""Shared test isolation for the offline suite.

Production callers of derive_edges() (analyze, audits, graph load) intentionally write
data/rejected/large_author_papers.jsonl. Unit tests call the same function with fixture
rows, which used to overwrite that tracked artifact with an empty list on every run and
silently change report counts. Redirect the module-level rejection directory to tmp_path
for every test so fixture writes stay inside the test's own sandbox. Module-scoped fixtures
are set up before this function-scoped fixture and must opt out explicitly with
derive_edges(..., write_rejections=False) when they do not need rejection artifacts.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_rejection_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr("src.graph.derive.REJECTED", tmp_path)