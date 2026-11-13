import pytest

from graphrag.entity_linking import EntityLinker, normalize_name
from graphrag.graph.fake_graph import FakeGraphRepository
from graphrag.models import EntityMention


@pytest.fixture
def linker() -> EntityLinker:
    return EntityLinker(FakeGraphRepository(), score_threshold=90, score_margin=8)


def test_normalize_name_handles_case_and_whitespace() -> None:
    assert normalize_name("  AN   Nguyen ") == "an nguyen"


@pytest.mark.asyncio
async def test_exact_name_links_to_stable_id(linker: EntityLinker) -> None:
    linked = await linker.link(EntityMention(text="An Nguyen", type="Author"))
    assert linked is not None
    assert linked.id == "author:an"
    assert linked.score == 100


@pytest.mark.asyncio
async def test_duplicate_exact_name_is_ambiguous(linker: EntityLinker) -> None:
    linked = await linker.link(EntityMention(text="Linh Nguyen", type="Author"))
    assert linked is not None
    assert linked.is_ambiguous
    assert {candidate.id for candidate in linked.ambiguous_candidates} == {
        "author:linh-a",
        "author:linh-b",
    }


@pytest.mark.asyncio
async def test_id_lookup_resolves_ambiguity(linker: EntityLinker) -> None:
    linked = await linker.link(EntityMention(text="author:linh-a", type="Author"))
    assert linked is not None
    assert linked.id == "author:linh-a"


@pytest.mark.asyncio
async def test_missing_name_returns_none(linker: EntityLinker) -> None:
    linked = await linker.link(EntityMention(text="Nobody In Corpus", type="Author"))
    assert linked is None
