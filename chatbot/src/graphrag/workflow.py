"""Bounded graph-only RAG coordinator."""

from __future__ import annotations

import time

from graphrag.answer import GroundedAnswerGenerator
from graphrag.entity_linking import EntityLinker
from graphrag.evidence import EvidenceNormalizer, build_citations
from graphrag.graph.base import GraphRepository
from graphrag.intent_parser import IntentParser
from graphrag.models import (
    CandidateEntity,
    ChatRequest,
    ChatResponse,
    QueryState,
    TraceStep,
)
from graphrag.planner import Planner
from graphrag.settings import Settings
from graphrag.sufficiency import decide_next


class GraphRAGWorkflow:
    def __init__(
        self,
        settings: Settings,
        repository: GraphRepository,
        parser: IntentParser,
        linker: EntityLinker,
        planner: Planner,
        answer_generator: GroundedAnswerGenerator,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.parser = parser
        self.linker = linker
        self.planner = planner
        self.answer_generator = answer_generator
        self.normalizer = EvidenceNormalizer()

    async def run(self, request: ChatRequest) -> ChatResponse:
        state = QueryState(question=request.question, max_iterations=self.settings.max_iterations)
        ambiguous_candidates: list[CandidateEntity] = []

        try:
            intent, parse_calls = await self.parser.parse(request.question)
            state.llm_calls += parse_calls
        except Exception as error:
            return self._error_response(f"intent_parse_error:{type(error).__name__}", request.debug)

        if intent.unsupported or intent.intent.value == "unknown":
            state.status = "out_of_scope"
            state.stop_reason = "unsupported_intent"
            state.answer = await self.answer_generator.generate(request.question, [], state.status)
            return self._response(state, request.debug, ambiguous_candidates)

        linked_results = await self.linker.link_all(intent.entities)
        for linked in linked_results:
            if linked is None:
                state.status = "not_found"
                state.stop_reason = "entity_not_found"
                state.answer = (
                    "Không nối được một thực thể trong câu hỏi với graph. Hãy dùng tên đầy đủ hoặc ID."
                )
                return self._response(state, request.debug, ambiguous_candidates)
            if linked.is_ambiguous:
                ambiguous_candidates.extend(linked.ambiguous_candidates)
            state.linked_entities.append(linked)

        if ambiguous_candidates:
            state.status = "ambiguous"
            state.stop_reason = "ambiguous_entity"
            state.answer = "Tên này khớp nhiều node. Hãy chọn một ID cụ thể rồi hỏi lại."
            return self._response(state, request.debug, ambiguous_candidates)

        try:
            state.planned_steps = self.planner.plan(intent, state.linked_entities)
        except ValueError as error:
            state.status = "not_found"
            state.stop_reason = "missing_required_entity"
            state.answer = str(error)
            return self._response(state, request.debug, ambiguous_candidates)

        state.goals_remaining = [step.fingerprint for step in state.planned_steps]
        if not state.planned_steps:
            state.status = "out_of_scope"
            state.stop_reason = "no_catalog_action"
            state.answer = await self.answer_generator.generate(request.question, [], state.status)
            return self._response(state, request.debug, ambiguous_candidates)

        existing_fact_ids: set[str] = set()
        for step in state.planned_steps:
            if state.iteration >= state.max_iterations:
                state.stop_reason = "max_iterations"
                break
            if step.fingerprint in state.seen_fingerprints:
                state.stop_reason = "duplicate_step"
                break

            started = time.perf_counter()
            state.seen_fingerprints.add(step.fingerprint)
            try:
                result = await self.repository.execute(step)
            except Exception as error:
                state.status = "error"
                state.stop_reason = f"graph_error:{type(error).__name__}"
                state.trace.append(
                    TraceStep(
                        iteration=state.iteration,
                        action=step.action,
                        status="error",
                        detail=type(error).__name__,
                    )
                )
                break

            state.iteration += 1
            new_facts = self.normalizer.normalize(result.records)
            delta = [fact for fact in new_facts if fact.fact_id not in existing_fact_ids]
            for fact in delta:
                existing_fact_ids.add(fact.fact_id)
            state.facts.extend(delta)
            state.executed.append(step)
            if step.fingerprint in state.goals_remaining:
                state.goals_remaining.remove(step.fingerprint)
            duration_ms = int((time.perf_counter() - started) * 1000)
            state.trace.append(
                TraceStep(
                    iteration=state.iteration,
                    action=step.action,
                    records=len(result.records),
                    new_facts=len(delta),
                    duration_ms=duration_ms,
                    status="ok" if result.records else "empty",
                    detail="results truncated" if result.truncated else None,
                )
            )
            decision = decide_next(state, len(delta))
            if decision.sufficient:
                state.stop_reason = "sufficient"
                break
            if decision.reason_code == "no_progress":
                state.stop_reason = "no_progress"
                break

        if state.status != "error":
            if state.facts and not state.goals_remaining:
                state.status = "answered"
                state.stop_reason = state.stop_reason or "sufficient"
            elif state.facts:
                state.status = "partial"
                state.stop_reason = state.stop_reason or "incomplete"
            else:
                state.status = "not_found"
                state.stop_reason = state.stop_reason or "empty_result"

        state.sources = build_citations(state.facts)
        state.answer = await self.answer_generator.generate(request.question, state.facts, state.status)
        state.llm_calls += 1
        return self._response(state, request.debug, ambiguous_candidates)

    def _response(
        self,
        state: QueryState,
        debug: bool,
        ambiguous_candidates: list[CandidateEntity],
    ) -> ChatResponse:
        watermark = None
        if self.settings.app_mode == "fake":
            watermark = "SIMULATED — no real LLM/DB"
        return ChatResponse(
            answer=state.answer,
            status=state.status,
            complete=state.status == "answered",
            iterations_used=state.iteration,
            stop_reason=state.stop_reason or "unknown",
            sources=state.sources,
            facts_count=len(state.facts),
            trace=state.trace if debug and self.settings.debug_traces else None,
            provider_info={
                "mode": self.settings.app_mode,
                "llm": self.settings.llm_provider,
                "graph": self.settings.graph_provider,
            },
            ambiguous_candidates=ambiguous_candidates,
            watermark=watermark,
        )

    def _error_response(self, reason: str, debug: bool) -> ChatResponse:
        return ChatResponse(
            answer="Không thể xử lý câu hỏi do lỗi đầu vào mô hình. Không có kết quả giả được thay thế.",
            status="error",
            complete=False,
            iterations_used=0,
            stop_reason=reason,
            facts_count=0,
            trace=[] if debug else None,
            provider_info={
                "mode": self.settings.app_mode,
                "llm": self.settings.llm_provider,
                "graph": self.settings.graph_provider,
            },
            watermark="SIMULATED — no real LLM/DB" if self.settings.app_mode == "fake" else None,
        )
