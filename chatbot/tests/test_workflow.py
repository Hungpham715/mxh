import pytest

from graphrag.factory import build_dependencies
from graphrag.graph.fake_graph import FakeGraphRepository
from graphrag.models import ChatRequest, QueryAction, QueryStep
from graphrag.settings import Settings


@pytest.fixture
def dependencies():
    return build_dependencies(Settings())


@pytest.mark.asyncio
async def test_one_hop_stops_after_one_query(dependencies) -> None:
    _, _, workflow = dependencies
    response = await workflow.run(ChatRequest(question="An Nguyen có những bài báo nào?", debug=True))
    assert response.status == "answered"
    assert response.iterations_used == 1
    assert response.stop_reason == "sufficient"
    assert response.sources


@pytest.mark.asyncio
async def test_overview_uses_two_bounded_iterations(dependencies) -> None:
    _, _, workflow = dependencies
    response = await workflow.run(ChatRequest(question="Tổng quan về An Nguyen", debug=True))
    assert response.status == "answered"
    assert response.iterations_used == 2
    assert [step.action for step in response.trace] == ["author_papers", "author_affiliations"]


@pytest.mark.asyncio
async def test_path_can_cover_multiple_hops_in_one_iteration(dependencies) -> None:
    _, _, workflow = dependencies
    response = await workflow.run(
        ChatRequest(question="Đường kết nối giữa An Nguyen và Binh Tran?", debug=True)
    )
    assert response.status == "answered"
    assert response.iterations_used == 1
    assert response.trace[0].action == "author_path"


@pytest.mark.asyncio
async def test_max_iterations_never_exceeds_five(dependencies) -> None:
    _, _, workflow = dependencies
    response = await workflow.run(ChatRequest(question="Tổng quan về An Nguyen", debug=True))
    assert response.iterations_used <= 5


@pytest.mark.asyncio
async def test_ambiguous_name_stops_before_query(dependencies) -> None:
    _, _, workflow = dependencies
    response = await workflow.run(ChatRequest(question="Bài báo của Linh Nguyen", debug=True))
    assert response.status == "ambiguous"
    assert response.iterations_used == 0
    assert len(response.ambiguous_candidates) == 2


@pytest.mark.asyncio
async def test_unknown_entity_is_not_found(dependencies) -> None:
    _, _, workflow = dependencies
    response = await workflow.run(ChatRequest(question='Bài báo của "Nobody In Corpus"', debug=True))
    assert response.status in {"not_found", "out_of_scope"}
    assert response.iterations_used == 0


@pytest.mark.asyncio
async def test_fake_response_always_has_simulation_watermark(dependencies) -> None:
    _, _, workflow = dependencies
    response = await workflow.run(ChatRequest(question="Top tác giả có nhiều đồng tác giả nhất"))
    assert response.watermark == "SIMULATED — no real LLM/DB"


@pytest.mark.asyncio
async def test_all_catalog_actions_execute_on_fake_graph() -> None:
    graph = FakeGraphRepository()
    params = {
        QueryAction.AUTHOR_PAPERS: {"author_id": "author:an", "year_from": None, "year_to": None},
        QueryAction.COAUTHORS: {"author_id": "author:an"},
        QueryAction.SHARED_PAPERS: {"author_id": "author:an", "other_author_id": "author:binh"},
        QueryAction.AUTHOR_AFFILIATIONS: {"author_id": "author:an"},
        QueryAction.COAUTHOR_AFFILIATIONS: {"author_id": "author:an"},
        QueryAction.PAPER_AUTHORS: {"paper_id": "paper:rag"},
        QueryAction.TOPIC_PAPERS: {"topic_id": "topic:retrieval", "year_from": None, "year_to": None},
        QueryAction.PAPER_VENUE: {"paper_id": "paper:rag"},
        QueryAction.PAPER_CITATIONS: {"paper_id": "paper:rag", "direction": "both"},
        QueryAction.ORG_COLLABORATIONS: {"institution_id": "inst:hust"},
        QueryAction.AUTHOR_PATH: {"author_id": "author:an", "other_author_id": "author:binh"},
        QueryAction.NETWORK_TOP: {},
        QueryAction.PAPER_METHODS: {"paper_id": "paper:rag"},
        QueryAction.METHOD_PAPERS: {
            "method_id": "method:graphrag",
            "year_from": None,
            "year_to": None,
        },
        QueryAction.PAPER_DATASETS: {"paper_id": "paper:rag"},
        QueryAction.DATASET_PAPERS: {
            "dataset_id": "dataset:nlpgraph-bench",
            "year_from": None,
            "year_to": None,
        },
        QueryAction.PAPER_TASKS: {"paper_id": "paper:rag"},
        QueryAction.TASK_PAPERS: {
            "task_id": "task:question-answering",
            "year_from": None,
            "year_to": None,
        },
        QueryAction.METHOD_TRENDS: {"year_from": None, "year_to": None},
    }
    for action in QueryAction:
        result = await graph.execute(
            QueryStep(action=action, params=params[action], expected_fields=[], limit=20)
        )
        assert result.records, action


@pytest.mark.asyncio
async def test_coauthor_affiliation_uses_only_shared_paper_evidence() -> None:
    graph = FakeGraphRepository()
    result = await graph.execute(
        QueryStep(
            action=QueryAction.COAUTHOR_AFFILIATIONS,
            params={"author_id": "author:an"},
            expected_fields=[],
        )
    )
    binh_rows = [row for row in result.records if row["value"]["coauthor_id"] == "author:binh"]
    assert len(binh_rows) == 1
    assert binh_rows[0]["object_id"] == "inst:vnu"
    assert binh_rows[0]["paper_ids"] == ["paper:rag"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "intent", "expected_value"),
    [
        ("Bài Graph Evidence for NLP sử dụng phương pháp nào?", "paper_methods", "GraphRAG"),
        ("Những bài nào sử dụng phương pháp GraphRAG?", "method_papers", "Graph Evidence for NLP"),
        ("Bài Graph Evidence for NLP được đánh giá trên bộ dữ liệu nào?", "paper_datasets", "NLPGraph Bench"),
        ("Những bài nào được đánh giá trên NLPGraph Bench?", "dataset_papers", "Graph Evidence for NLP"),
        ("Bài Graph Evidence for NLP giải quyết bài toán nào?", "paper_tasks", "Question Answering"),
        ("Những bài nào giải quyết bài toán Question Answering?", "task_papers", "Graph Evidence for NLP"),
    ],
)
async def test_enrichment_questions_use_graph_evidence(
    dependencies, question: str, intent: str, expected_value: str
) -> None:
    _, _, workflow = dependencies
    response = await workflow.run(ChatRequest(question=question, debug=True))
    assert response.status == "answered"
    assert response.parsed_intent == intent
    assert expected_value in response.answer
    assert response.sources
    assert response.trace and response.trace[0].action == intent


@pytest.mark.asyncio
async def test_method_trends_return_db_derived_counts(dependencies) -> None:
    _, _, workflow = dependencies
    response = await workflow.run(
        ChatRequest(question="Phương pháp nào được dùng nhiều nhất trong corpus?", debug=True)
    )
    assert response.status == "answered"
    assert response.parsed_intent == "method_trends"
    assert "(1 bài)" in response.answer
    assert response.sources


class DuplicatePlanner:
    def plan(self, intent, linked, page_size=None):
        _ = intent, page_size
        step = QueryStep(
            action=QueryAction.AUTHOR_PAPERS,
            params={"author_id": linked[0].id, "year_from": None, "year_to": None},
            expected_fields=[],
        )
        return [step, step]


@pytest.mark.asyncio
async def test_duplicate_step_stops_loop(dependencies) -> None:
    _, _, workflow = dependencies
    workflow.planner = DuplicatePlanner()
    response = await workflow.run(ChatRequest(question="Bài báo của An Nguyen", debug=True))
    assert response.iterations_used == 1
    assert response.status == "partial"
    assert response.stop_reason == "duplicate_step"


class TimeoutRepository(FakeGraphRepository):
    async def execute(self, step):
        _ = step
        raise TimeoutError("synthetic timeout")


@pytest.mark.asyncio
async def test_database_timeout_returns_error_without_fake_fallback(dependencies) -> None:
    _, _, workflow = dependencies
    workflow.repository = TimeoutRepository()
    response = await workflow.run(ChatRequest(question="Bài báo của An Nguyen", debug=True))
    assert response.status == "error"
    assert response.iterations_used == 0
    assert response.stop_reason == "graph_error:TimeoutError"
