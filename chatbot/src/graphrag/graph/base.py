"""Repository boundary for graph query execution and entity catalogs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from graphrag.models import QueryStep


@dataclass(frozen=True)
class EntityRecord:
    id: str
    label: str
    name: str
    identity_status: str | None = None


@dataclass(frozen=True)
class GraphQueryResult:
    """One page of rows. `truncated` means more rows exist after this page; `total` is the
    full row count of the action (None when not computed because the page was complete)."""

    records: list[dict[str, Any]]
    truncated: bool = False
    total: int | None = None


class GraphRepository(Protocol):
    name: str

    async def entity_catalog(self, *, force_refresh: bool = False) -> list[EntityRecord]: ...

    async def execute(self, step: QueryStep) -> GraphQueryResult: ...

    async def health(self) -> tuple[bool, str]: ...

    async def preview(self) -> dict[str, Any]: ...

    async def close(self) -> None: ...
