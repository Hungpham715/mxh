"""FastAPI transport for non-streaming and POST-based SSE chat."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from graphrag.factory import build_dependencies
from graphrag.models import ChatRequest, ChatResponse
from graphrag.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings.from_env()
    llm, repository, workflow = build_dependencies(resolved)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = resolved
        app.state.llm = llm
        app.state.repository = repository
        app.state.workflow = workflow
        yield
        await repository.close()
        await llm.close()

    app = FastAPI(title="MXH NLP GraphRAG", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[resolved.frontend_origin],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as error:
            payload = {
                "error": {
                    "code": "internal_error",
                    "message": "The request could not be completed.",
                    "type": type(error).__name__,
                    "request_id": request_id,
                }
            }
            response = JSONResponse(payload, status_code=500)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-Ms"] = str(int((time.perf_counter() - started) * 1000))
        return response

    @app.get("/api/config/public")
    async def public_config() -> dict[str, object]:
        return resolved.public_dict()

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        llm_ok, llm_detail = await llm.health()
        graph_ok, graph_detail = await repository.health()
        overall = "ok" if llm_ok and graph_ok else "degraded"
        return {
            "status": overall,
            "mode": resolved.app_mode,
            "llm": {"provider": resolved.llm_provider, "ready": llm_ok, "detail": llm_detail},
            "graph": {"provider": resolved.graph_provider, "ready": graph_ok, "detail": graph_detail},
        }

    @app.get("/api/graph/preview")
    async def graph_preview() -> dict[str, Any]:
        return await repository.preview()

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(payload: ChatRequest) -> ChatResponse:
        return await asyncio.wait_for(workflow.run(payload), timeout=resolved.request_timeout_seconds)

    @app.post("/api/chat/stream")
    async def chat_stream(payload: ChatRequest) -> StreamingResponse:
        if not resolved.enable_sse:
            return StreamingResponse(_single_error_event("sse_disabled"), media_type="text/event-stream")

        async def events():
            yield _event("start", {"mode": resolved.app_mode})
            await asyncio.sleep(0)
            try:
                response = await asyncio.wait_for(
                    workflow.run(payload),
                    timeout=resolved.request_timeout_seconds,
                )
            except TimeoutError:
                yield _event("error", {"code": "request_timeout"})
                return
            yield _event("parse", {"status": response.status})
            yield _event(
                "linked",
                {
                    "status": response.status,
                    "ambiguity": [item.model_dump(mode="json") for item in response.ambiguous_candidates],
                },
            )
            for trace in response.trace or []:
                yield _event(
                    "query_start",
                    {
                        "iteration": trace.iteration,
                        "action": trace.action,
                    },
                )
                yield _event("query_result", trace.model_dump(mode="json"))
                yield _event(
                    "decision",
                    {
                        "iteration": trace.iteration,
                        "decision": trace.status,
                        "new_facts": trace.new_facts,
                    },
                )
                await asyncio.sleep(0)
            yield _event("answer", {"answer": response.answer})
            yield _event("done", response.model_dump(mode="json"))

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


def _event(name: str, data: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _single_error_event(code: str):
    yield _event("error", {"code": code})


app = create_app()
