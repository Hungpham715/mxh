import json

import httpx
import pytest

from graphrag.api import create_app
from graphrag.settings import Settings


@pytest.fixture
async def client():
    app = create_app(Settings())
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as api_client:
            yield api_client


@pytest.mark.asyncio
async def test_health_and_public_config_do_not_expose_secrets(client) -> None:
    health = await client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["mode"] == "fake"
    config = await client.get("/api/config/public")
    assert "password" not in json.dumps(config.json()).lower()


@pytest.mark.asyncio
async def test_atlas_serves_real_snapshot_even_when_chat_profile_is_fake(client) -> None:
    response = await client.get("/api/atlas")
    assert response.status_code == 200
    payload = response.json()
    assert payload["source_kind"] == "real_offline_snapshot"
    assert payload["counts"]["nodes"]["Paper"] == 1091
    assert payload["graph"]["nodes"] and payload["graph"]["edges"]
    assert "watermark" not in payload


@pytest.mark.asyncio
async def test_atlas_missing_snapshot_fails_explicitly_without_fake_fallback(tmp_path) -> None:
    app = create_app(Settings(atlas_data_dir=tmp_path))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as api_client:
            response = await api_client.get("/api/atlas")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "atlas_snapshot_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "An Nguyen có những bài báo nào?",
        "Đồng tác giả của An Nguyen là ai?",
        "An Nguyen và Binh Tran có bài chung nào?",
        "Tổ chức của An Nguyen theo bài báo?",
        "Ai viết Graph Evidence for NLP?",
        "Graph Evidence for NLP đăng ở venue nào?",
    ],
)
async def test_six_fake_chat_questions_match_contract(client, question: str) -> None:
    response = await client.post("/api/chat", json={"question": question, "debug": True})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] in {"answered", "partial", "not_found", "ambiguous"}
    assert payload["iterations_used"] <= 5
    assert payload["watermark"] == "SIMULATED — no real LLM/DB"


@pytest.mark.asyncio
async def test_stream_done_payload_matches_non_stream_response(client) -> None:
    request = {"question": "Bài báo của An Nguyen", "debug": True}
    regular = (await client.post("/api/chat", json=request)).json()
    streamed = await client.post("/api/chat/stream", json=request)
    assert streamed.status_code == 200
    events = []
    current_event = None
    for line in streamed.text.splitlines():
        if line.startswith("event: "):
            current_event = line.removeprefix("event: ")
        if line.startswith("data: "):
            events.append((current_event, json.loads(line.removeprefix("data: "))))
    names = [name for name, _ in events]
    assert names[0:3] == ["start", "parse", "linked"]
    assert {"query_start", "query_result", "decision", "answer", "done"} <= set(names)
    done = [data for name, data in events if name == "done"][0]
    assert done == regular


@pytest.mark.asyncio
async def test_request_length_is_validated(client) -> None:
    response = await client.post("/api/chat", json={"question": "x" * 2001})
    assert response.status_code == 422
