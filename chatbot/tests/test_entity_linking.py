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


@pytest.mark.asyncio
async def test_rescue_recovers_single_author_from_question(linker: EntityLinker) -> None:
    mentions = await linker.rescue_mentions("author_papers", "Các bài báo của An Nguyen?", [])
    assert [m.text for m in mentions] == ["An Nguyen"]
    assert mentions[0].type == "Author"


@pytest.mark.asyncio
async def test_rescue_recovers_two_authors_longest_first(linker: EntityLinker) -> None:
    mentions = await linker.rescue_mentions("shared_papers", "Bài chung của An Nguyen và Binh Tran?", [])
    assert {m.text for m in mentions} == {"An Nguyen", "Binh Tran"}


@pytest.mark.asyncio
async def test_rescue_uses_history_for_pronoun(linker: EntityLinker) -> None:
    history = [{"role": "user", "content": "Liệt kê bài báo của Binh Tran"}]
    mentions = await linker.rescue_mentions("coauthors", "Đồng tác giả của người đó?", history)
    assert [m.text for m in mentions] == ["Binh Tran"]


@pytest.mark.asyncio
async def test_rescue_returns_empty_for_entity_free_intent(linker: EntityLinker) -> None:
    assert await linker.rescue_mentions("network_top", "Top tác giả?", []) == []


@pytest.mark.asyncio
async def test_rescue_returns_empty_when_name_absent(linker: EntityLinker) -> None:
    mentions = await linker.rescue_mentions("author_papers", "Bài báo của ai đó lạ?", [])
    assert mentions == []
