"""Bounded graph-only RAG coordinator with live event streaming.

`run_events` is the single execution path: it yields (event_name, data) tuples *while* the
retrieval loop runs, so the SSE endpoint streams real progress. `run` consumes the same
generator and returns the final ChatResponse, keeping non-stream and stream semantics equal.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Iterator
from typing import Any

from graphrag.answer import GroundedAnswerGenerator
from graphrag.entity_linking import INTENT_REQUIRED_MENTIONS, EntityLinker, is_pronoun_reference
from graphrag.evidence import EvidenceNormalizer, build_citations
from graphrag.graph.base import GraphRepository
from graphrag.intent_parser import IntentParser
from graphrag.models import (
    CandidateEntity,
    ChatRequest,
    ChatResponse,
    IntentName,
    NextDecision,
    QueryIntent,
    QueryState,
    QueryStep,
    RouteName,
    TraceStep,
)
from graphrag.next_step import NextStepDecider
from graphrag.planner import EXPECTED_FIELDS, Planner
from graphrag.settings import Settings
from graphrag.sufficiency import hard_stop_reason


class GraphRAGWorkflow:
    def __init__(
        self,
        settings: Settings,
        repository: GraphRepository,
        parser: IntentParser,
        linker: EntityLinker,
        planner: Planner,
        answer_generator: GroundedAnswerGenerator,
        next_step_decider: NextStepDecider | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.parser = parser
        self.linker = linker
        self.planner = planner
        self.answer_generator = answer_generator
        self.next_step = next_step_decider
        self.normalizer = EvidenceNormalizer()

    async def run(self, request: ChatRequest) -> ChatResponse:
        final: ChatResponse | None = None
        async for name, data in self.run_events(request):
            if name == "done":
                final = ChatResponse.model_validate(data)
        if final is None:  # pragma: no cover - generator always ends with done
            return self._error_response("stream_ended_without_done", request.debug)
        return final

    async def run_events(self, request: ChatRequest) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        history = [message.model_dump() for message in request.history]
        state = QueryState(question=request.question, max_iterations=self.settings.max_iterations)
        ambiguous_candidates: list[CandidateEntity] = []

        yield (
            "start",
            {
                "mode": self.settings.app_mode,
                "llm": self.settings.llm_provider,
                "graph": self.settings.graph_provider,
            },
        )

        try:
            intent, parse_calls = await self.parser.parse(request.question, history)
            state.llm_calls += parse_calls
        except Exception as error:
            response = self._error_response(f"intent_parse_error:{type(error).__name__}", request.debug)
            yield "done", response.model_dump(mode="json")
            return

        # A 0.6B router can emit valid JSON while confusing relationships that use the same entity
        # type (for example coauthors vs author_papers). When exact live-catalog names are present,
        # give the LLM one focused verification turn. Intent selection remains with the model;
        # code only constrains accepted entities to trusted catalog spans.
        catalog_mentions = await self.linker.catalog_mentions(request.question)
        weak_without_catalog = not catalog_mentions and (
            (intent.route == RouteName.CLARIFY and (intent.intent.value == "unknown" or not intent.entities))
            or (
                intent.route == RouteName.GRAPH_QA
                and bool(intent.entities)
                and all(entity.type == "Unknown" for entity in intent.entities)
            )
        )
        if weak_without_catalog:
            verified_route, route_calls = await self.parser.verify_route_without_catalog(
                request.question, history, intent
            )
            state.llm_calls += route_calls
            if verified_route == RouteName.OUT_OF_SCOPE:
                intent = intent.model_copy(
                    update={
                        "route": RouteName.OUT_OF_SCOPE,
                        "intent": IntentName.UNKNOWN,
                        "entities": [],
                        "missing_fields": [],
                        "unsupported": True,
                    }
                )
        required = INTENT_REQUIRED_MENTIONS.get(intent.intent.value)
        catalog_conflict = (
            required is not None
            and sum(mention.type == required[0] for mention in catalog_mentions) < required[1]
        )
        weak_parse = bool(catalog_mentions) and (
            intent.route == RouteName.OUT_OF_SCOPE or intent.intent.value == "unknown" or catalog_conflict
        )
        verify_graph_parse = bool(catalog_mentions) and intent.route in {
            RouteName.GRAPH_QA,
            RouteName.CLARIFY,
        }
        if weak_parse or verify_graph_parse:
            repaired, repair_calls = await self.parser.repair_with_catalog_context(
                request.question,
                history,
                intent,
                catalog_mentions,
            )
            state.llm_calls += repair_calls
            if repaired is not None:
                chosen = repaired.intent
                if repaired.intent != intent.intent and not catalog_conflict and required is not None:
                    chosen, arbitration_calls = await self.parser.choose_between_intents(
                        request.question,
                        intent.intent,
                        repaired.intent,
                    )
                    state.llm_calls += arbitration_calls
                if chosen == repaired.intent:
                    intent = repaired
                    state.entity_rescue = "catalog_verified_llm"

        if intent.route in {RouteName.GRAPH_QA, RouteName.CLARIFY} and intent.intent.value != "unknown":
            count_fields, field_calls = await self.parser.classify_requested_fields(
                request.question, intent.intent.value
            )
            state.llm_calls += field_calls
            requested_fields = [field for field in intent.requested_fields if field != "count"]
            requested_fields.extend(count_fields)
            intent = intent.model_copy(update={"requested_fields": requested_fields})

        yield (
            "parse",
            {
                "route": intent.route.value,
                "intent": intent.intent.value,
                "parse_source": intent.parse_source,
                "entities": [entity.model_dump(mode="json") for entity in intent.entities],
                "missing_fields": intent.missing_fields,
            },
        )

        # --- Deterministic catalog rescue (code-owned fallback) ---------------
        # If the model committed to a concrete graph intent, prefer exact catalog names found
        # verbatim in the question (or history for an explicit pronoun). This also repairs a
        # misspelled/overlong model span and lets a resolvable follow-up leave CLARIFY. It never
        # fires for unknown/entity-free intents or invents an entity absent from the input.
        required = INTENT_REQUIRED_MENTIONS.get(intent.intent.value)
        if intent.route in {RouteName.GRAPH_QA, RouteName.CLARIFY} and required is not None:
            rescued = await self.linker.rescue_mentions(intent.intent.value, request.question, history)
            if len(rescued) >= required[1]:
                intent = intent.model_copy(
                    update={"entities": rescued, "route": RouteName.GRAPH_QA, "missing_fields": []}
                )
                state.entity_rescue = state.entity_rescue or "catalog"
                if not catalog_mentions:
                    # The question itself names nobody, so the rescue came from history. Follow-up
                    # questions carry the relationship in words like "đồng tác giả", which a 0.6B
                    # model often mis-maps on first parse; give the LLM one focused verification
                    # turn against the recovered catalog entities (same contract as the pre-link
                    # repair pass — the model decides, code only supplies trusted mentions).
                    repaired, repair_calls = await self.parser.repair_with_catalog_context(
                        request.question, history, intent, rescued
                    )
                    state.llm_calls += repair_calls
                    if repaired is not None:
                        intent = repaired
                        state.entity_rescue = "catalog_verified_llm"

        # An entity-bearing intent whose question names nobody is a clarification, not a lookup
        # failure: `not_found` must mean a concrete name was given but is absent from the catalog.
        # After grounding dropped hallucinated spans and the catalog rescue found nothing, only
        # pronoun-style references (or nothing) remain — ask the user for the missing name.
        if intent.route == RouteName.GRAPH_QA and required is not None:
            named_mentions = [
                mention for mention in intent.entities if not is_pronoun_reference(mention.text)
            ]
            if not named_mentions:
                intent = intent.model_copy(
                    update={
                        "route": RouteName.CLARIFY,
                        "entities": [],
                        "missing_fields": [f"{required[0].casefold()}_reference"],
                    }
                )

        # --- Route dispatch -------------------------------------------------
        if intent.route == RouteName.OUT_OF_SCOPE or intent.unsupported:
            state.status = "out_of_scope"
            state.stop_reason = "unsupported_intent"
            state.answer = await self.answer_generator.generate(request.question, [], state.status)
            state.llm_calls += 1
            for event in self._finish(state, request, ambiguous_candidates, intent):
                yield event
            return

        if intent.route == RouteName.CHAT_HISTORY:
            state.status = "answered"
            state.stop_reason = "chat_history"
            state.answer = await self.answer_generator.generate_from_history(request.question, history)
            state.llm_calls += 1
            for event in self._finish(state, request, ambiguous_candidates, intent):
                yield event
            return

        if intent.route == RouteName.CLARIFY:
            state.status = "clarify"
            state.stop_reason = "clarify_missing_fields"
            state.answer = self._clarify_question(intent.missing_fields)
            for event in self._finish(state, request, ambiguous_candidates, intent):
                yield event
            return

        if intent.intent.value == "unknown":
            # A pronoun-style reference with no resolvable antecedent is under-referenced, not
            # off-topic: ask for the missing name instead of refusing.
            if is_pronoun_reference(request.question):
                intent = intent.model_copy(update={"route": RouteName.CLARIFY})
                state.status = "clarify"
                state.stop_reason = "clarify_missing_fields"
                state.answer = self._clarify_question(intent.missing_fields)
                for event in self._finish(state, request, ambiguous_candidates, intent):
                    yield event
                return
            # GRAPH_QA route but no catalog intent: treat as out-of-scope, never guess.
            state.status = "out_of_scope"
            state.stop_reason = "unsupported_intent"
            state.answer = await self.answer_generator.generate(request.question, [], state.status)
            state.llm_calls += 1
            for event in self._finish(state, request, ambiguous_candidates, intent):
                yield event
            return

        # --- Entity linking ---------------------------------------------------
        linked_results = await self.linker.link_all(intent.entities)
        for linked in linked_results:
            if linked is None:
                state.status = "not_found"
                state.stop_reason = "entity_not_found"
                state.answer = (
                    "Không nối được một thực thể trong câu hỏi với graph. Hãy dùng tên đầy đủ hoặc ID."
                )
                for event in self._finish(state, request, ambiguous_candidates, intent):
                    yield event
                return
            if linked.is_ambiguous:
                ambiguous_candidates.extend(linked.ambiguous_candidates)
            state.linked_entities.append(linked)

        yield (
            "linked",
            {
                "status": "ok",
                "linked": [entity.model_dump(mode="json") for entity in state.linked_entities],
                "ambiguity": [item.model_dump(mode="json") for item in ambiguous_candidates],
            },
        )

        if ambiguous_candidates:
            state.status = "ambiguous"
            state.stop_reason = "ambiguous_entity"
            state.answer = "Tên này khớp nhiều node. Hãy chọn một ID cụ thể rồi hỏi lại."
            for event in self._finish(state, request, ambiguous_candidates, intent):
                yield event
            return

        # --- Plan + bounded retrieval loop -------------------------------------
        try:
            queue = self.planner.plan(intent, state.linked_entities, page_size=request.page_size)
        except ValueError as error:
            state.status = "not_found"
            state.stop_reason = "missing_required_entity"
            state.answer = str(error)
            for event in self._finish(state, request, ambiguous_candidates, intent):
                yield event
            return

        state.planned_steps = list(queue)
        state.goals_remaining = [step.fingerprint for step in queue]
        if not queue:
            state.status = "out_of_scope"
            state.stop_reason = "no_catalog_action"
            state.answer = await self.answer_generator.generate(request.question, [], state.status)
            state.llm_calls += 1
            for event in self._finish(state, request, ambiguous_candidates, intent):
                yield event
            return

        existing_fact_ids: set[str] = set()
        new_fact_count = 0
        while state.iteration < state.max_iterations:
            step = queue.pop(0) if queue else None
            if step is None:
                # Queue exhausted: the LLM decides whether the question is answered or which
                # catalog action runs next. Hard guards (no progress / budget) stay in code.
                if self.next_step is None:
                    state.stop_reason = state.stop_reason or "sufficient"
                    break
                decision, llm_calls = await self.next_step.decide(
                    request.question,
                    intent.intent.value,
                    intent.requested_fields,
                    state,
                    new_fact_count,
                )
                state.llm_calls += llm_calls
                yield "decision", self._decision_payload(state.iteration, decision, new_fact_count)
                if decision.sufficient:
                    state.stop_reason = "sufficient"
                    break
                if decision.reason_code == "no_progress":
                    state.stop_reason = "no_progress"
                    break
                if decision.reason_code == "limit_reached":
                    state.stop_reason = "max_iterations"
                    break
                if decision.reason_code == "missing_entity":
                    state.status = "clarify"
                    state.stop_reason = "missing_entity"
                    state.answer = self._clarify_question(decision.missing_goals)
                    for event in self._finish(state, request, ambiguous_candidates, intent):
                        yield event
                    return
                if decision.reason_code == "invalid_decision" or decision.next_action is None:
                    state.stop_reason = "invalid_next_step"
                    break
                step = QueryStep(
                    action=decision.next_action,
                    params=decision.params or {},
                    expected_fields=EXPECTED_FIELDS[decision.next_action],
                    limit=request.page_size,
                )

            if step.fingerprint in state.seen_fingerprints:
                state.stop_reason = "duplicate_step"
                break

            started = time.perf_counter()
            state.seen_fingerprints.add(step.fingerprint)
            yield "query_start", {"iteration": state.iteration + 1, "action": step.action}
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
                yield "query_result", state.trace[-1].model_dump(mode="json")
                break

            state.iteration += 1
            if result.truncated:
                state.truncated = True
            new_facts = self.normalizer.normalize(result.records)
            delta = [fact for fact in new_facts if fact.fact_id not in existing_fact_ids]
            for fact in delta:
                existing_fact_ids.add(fact.fact_id)
            state.facts.extend(delta)
            state.executed.append(step)
            if step.fingerprint in state.goals_remaining:
                state.goals_remaining.remove(step.fingerprint)
            new_fact_count = len(delta)
            duration_ms = int((time.perf_counter() - started) * 1000)
            trace_step = TraceStep(
                iteration=state.iteration,
                action=step.action,
                records=len(result.records),
                new_facts=len(delta),
                duration_ms=duration_ms,
                status="ok" if result.records else "empty",
                detail="results truncated" if result.truncated else None,
            )
            state.trace.append(trace_step)
            yield "query_result", trace_step.model_dump(mode="json")

            # Code-owned guards after every executed step (no LLM involved).
            guard_stop = hard_stop_reason(state, new_fact_count, queue_empty=not queue)
            if guard_stop == "no_progress":
                state.stop_reason = "no_progress"
                yield (
                    "decision",
                    {
                        "iteration": state.iteration,
                        "decision": "no_progress",
                        "new_facts": 0,
                    },
                )
                break

        if state.iteration >= state.max_iterations and state.stop_reason is None:
            state.stop_reason = "max_iterations"

        if state.status not in {"error", "clarify"}:
            if state.facts and state.stop_reason == "sufficient":
                state.status = "partial" if state.truncated else "answered"
            elif state.facts:
                state.status = "partial"
                state.stop_reason = state.stop_reason or "incomplete"
            else:
                state.status = "not_found"
                state.stop_reason = state.stop_reason or "empty_result"

        state.answer = await self.answer_generator.generate(
            request.question,
            state.facts,
            state.status,
            truncated=state.truncated,
            requested_fields=intent.requested_fields,
        )
        if state.facts:
            state.llm_calls += 1
        for event in self._finish(state, request, ambiguous_candidates, intent):
            yield event

    # --- helpers ---------------------------------------------------------------

    def _finish(
        self,
        state: QueryState,
        request: ChatRequest,
        ambiguous_candidates: list[CandidateEntity],
        intent: QueryIntent | None,
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        state.sources = build_citations(state.facts)
        response = self._response(state, request.debug, ambiguous_candidates, intent)
        yield "answer", {"answer": response.answer, "status": response.status}
        yield "done", response.model_dump(mode="json")

    @staticmethod
    def _decision_payload(iteration: int, decision: NextDecision, new_facts: int) -> dict[str, Any]:
        return {
            "iteration": iteration,
            "decision": decision.reason_code,
            "sufficient": decision.sufficient,
            "next_action": decision.next_action.value if decision.next_action else None,
            "new_facts": new_facts,
        }

    @staticmethod
    def _clarify_question(missing_fields: list[str]) -> str:
        if any("author" in field for field in missing_fields):
            return "Bạn muốn hỏi về tác giả nào? Hãy cho tôi tên tác giả cụ thể."
        if any("paper" in field for field in missing_fields):
            return "Bạn muốn hỏi về bài báo nào? Hãy cho tôi tiêu đề hoặc ID bài báo."
        return "Câu hỏi chưa rõ tham chiếu. Hãy cho biết tên tác giả, bài báo hoặc tổ chức cụ thể."

    def _response(
        self,
        state: QueryState,
        debug: bool,
        ambiguous_candidates: list[CandidateEntity],
        intent: QueryIntent | None = None,
    ) -> ChatResponse:
        watermark = None
        if self.settings.app_mode == "fake":
            watermark = "SIMULATED — no real LLM/DB"
        return ChatResponse(
            answer=state.answer,
            status=state.status,
            complete=state.status == "answered" and not state.truncated,
            iterations_used=state.iteration,
            stop_reason=state.stop_reason or "unknown",
            sources=state.sources,
            facts_count=len(state.facts),
            truncated=state.truncated,
            route=intent.route if intent is not None else None,
            parsed_intent=intent.intent.value if intent is not None else None,
            parse_source=intent.parse_source if intent is not None else None,
            parsed_entities=list(intent.entities) if intent is not None else [],
            linked_entities=list(state.linked_entities),
            entity_rescue=state.entity_rescue,
            llm_calls=state.llm_calls,
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
