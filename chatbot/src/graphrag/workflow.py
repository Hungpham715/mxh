"""Bounded graph-only RAG coordinator.

Flow: route/parse (LLM, validated) -> CHAT_HISTORY | CLARIFY | OUT_OF_SCOPE | GRAPH_QA.
GRAPH_QA: link entities -> plan first safe action -> query -> normalize facts ->
decide next step (hard rules first, then LLM TASK=NEXT_STEP validated by code) ->
repeat until goals satisfied / no progress / duplicate / max iterations -> grounded answer.

MAX_GRAPH_HOPS bounds edges inside one Cypher query; MAX_ITERATIONS bounds DB query steps.
Progress events are emitted while the loop runs (used by the SSE endpoint).
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError

from graphrag.answer import GroundedAnswerGenerator
from graphrag.entity_linking import EntityLinker
from graphrag.evidence import EvidenceNormalizer, build_citations
from graphrag.graph.base import GraphRepository
from graphrag.intent_parser import REQUIRED_ENTITIES, IntentParser
from graphrag.llm.prompts import NEXT_STEP_SYSTEM
from graphrag.models import (
    CandidateEntity,
    ChatRequest,
    ChatResponse,
    ChatTurn,
    Continuation,
    EntityMention,
    IntentName,
    MoreRequest,
    NextStepProposal,
    QueryIntent,
    QueryState,
    QueryStep,
    RouteName,
    TraceStep,
)
from graphrag.planner import Planner
from graphrag.settings import Settings

EmitFn = Callable[[str, dict[str, Any]], Awaitable[None]]


async def _no_emit(name: str, data: dict[str, Any]) -> None:
    _ = name, data


CLARIFY_TEXT = {
    "author_reference": "Bạn muốn hỏi về tác giả nào? Hãy cho biết tên đầy đủ của tác giả.",
    "paper_reference": "Bạn muốn hỏi về bài báo nào? Hãy cho biết tiêu đề hoặc ID bài báo.",
    "topic_reference": "Bạn muốn hỏi về chủ đề nào (ví dụ: Machine translation, Question answering)?",
    "institution_reference": "Bạn muốn hỏi về tổ chức nào? Hãy cho biết tên tổ chức.",
}


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

    async def run(self, request: ChatRequest, emit: EmitFn | None = None) -> ChatResponse:
        emit = emit or _no_emit
        state = QueryState(question=request.question, max_iterations=self.settings.max_iterations)
        await emit("start", {"mode": self.settings.app_mode})

        try:
            intent, parse_calls = await self.parser.parse(request.question, request.history)
            state.llm_calls += parse_calls
        except Exception as error:
            await emit("error", {"code": "intent_parse_error", "type": type(error).__name__})
            return self._error_response(f"intent_parse_error:{type(error).__name__}", request.debug)

        intent, repair_calls = await self._repair_entities(intent, request.question, request.history)
        state.llm_calls += repair_calls
        state.route = intent.route
        await emit(
            "parse",
            {
                "route": intent.route.value,
                "intent": intent.intent.value,
                "entities": [entity.model_dump() for entity in intent.entities],
                "requested_fields": intent.requested_fields,
                "parse_source": intent.parse_source,
            },
        )

        if intent.route == RouteName.CHAT_HISTORY:
            state.status = "answered"
            state.stop_reason = "chat_history"
            state.answer, calls = await self.answer_generator.answer_history(
                request.question, request.history
            )
            state.llm_calls += calls
            return await self._finish(state, request.debug, [], intent.parse_source, emit)

        if intent.route == RouteName.OUT_OF_SCOPE:
            state.status = "out_of_scope"
            state.stop_reason = "unsupported_intent"
            state.answer = await self.answer_generator.generate(request.question, [], state.status)
            return await self._finish(state, request.debug, [], intent.parse_source, emit)

        if intent.route == RouteName.CLARIFY:
            state.status = "clarify"
            state.stop_reason = "needs_user_clarification"
            missing = intent.missing_fields[0] if intent.missing_fields else "author_reference"
            state.answer = CLARIFY_TEXT.get(
                missing, "Bạn có thể nói rõ thực thể (tác giả/bài báo/tổ chức) cần hỏi?"
            )
            return await self._finish(state, request.debug, [], intent.parse_source, emit)

        ambiguous_candidates: list[CandidateEntity] = []
        linked_results = await self.linker.link_all(intent.entities)
        for mention, linked in zip(intent.entities, linked_results, strict=True):
            if linked is None:
                state.status = "not_found"
                state.stop_reason = "entity_not_found"
                state.answer = (
                    f"Không tìm thấy “{mention.text}” trong graph (corpus NLP 2023–2025 được lấy mẫu). "
                    "Hãy kiểm tra chính tả hoặc dùng tên đầy đủ/ID."
                )
                await emit("linked", {"status": "not_found", "mention": mention.text})
                return await self._finish(state, request.debug, [], intent.parse_source, emit)
            if linked.is_ambiguous:
                ambiguous_candidates.extend(linked.ambiguous_candidates)
            state.linked_entities.append(linked)
        await emit(
            "linked",
            {
                "entities": [
                    {"id": item.id, "label": item.label, "name": item.name, "score": item.score}
                    for item in state.linked_entities
                ],
                "ambiguity": [item.model_dump(mode="json") for item in ambiguous_candidates],
            },
        )

        if ambiguous_candidates:
            state.status = "ambiguous"
            state.stop_reason = "ambiguous_entity"
            options = "; ".join(f"{item.name} ({item.id})" for item in ambiguous_candidates)
            state.answer = f"Tên này khớp nhiều node trong graph: {options}. Bạn muốn hỏi về ai/cái nào?"
            return await self._finish(state, request.debug, ambiguous_candidates, intent.parse_source, emit)

        try:
            first_steps = self.planner.plan(intent, state.linked_entities)
        except ValueError as error:
            state.status = "clarify"
            state.stop_reason = "missing_required_entity"
            state.answer = f"Câu hỏi còn thiếu thực thể cần thiết ({error}). Bạn có thể bổ sung không?"
            return await self._finish(state, request.debug, [], intent.parse_source, emit)
        if not first_steps:
            state.status = "out_of_scope"
            state.stop_reason = "no_catalog_action"
            state.answer = await self.answer_generator.generate(request.question, [], state.status)
            return await self._finish(state, request.debug, [], intent.parse_source, emit)

        state.goals_remaining = self.planner.goals(intent)
        await self._loop(state, first_steps[0], emit)

        if state.status != "error":
            truncated = bool(state.truncated_steps)
            if state.facts and not state.goals_remaining and not truncated:
                state.status = "answered"
                state.stop_reason = state.stop_reason or "sufficient"
            elif state.facts:
                state.status = "partial"
                state.stop_reason = state.stop_reason or ("truncated" if truncated else "incomplete")
            else:
                state.status = "not_found"
                state.stop_reason = state.stop_reason or "empty_result"

        state.sources = build_citations(state.facts)
        if state.facts:
            body = await self.answer_generator.generate(request.question, state.facts, state.status)
            state.llm_calls += 1
        else:
            body = await self.answer_generator.generate(request.question, [], state.status)
        state.answer = self._completeness_note(state) + body
        return await self._finish(state, request.debug, [], intent.parse_source, emit)

    async def _repair_entities(
        self, intent: QueryIntent, question: str, history: list[ChatTurn]
    ) -> tuple[QueryIntent, int]:
        """Contract repair after parsing (small models often drop or invent names).

        - Entities are completed from exact catalog names found in the question (entity linking),
          or, for a follow-up without any name, in the most recent user turn of the history.
        - CLARIFY is only valid when the required entity is truly absent, so it is overturned
          when the question does contain it.
        - If the entity type found does not fit the intent, the model chooses again among the
          intents valid for that type (TASK=CHOOSE_INTENT).
        """
        if intent.route not in {RouteName.GRAPH_QA, RouteName.CLARIFY}:
            return intent, 0
        if intent.intent in {IntentName.UNKNOWN, IntentName.NETWORK_TOP}:
            return intent, 0
        calls = 0
        entities = list(intent.entities)
        spotted = await self.linker.spot(question)
        if not spotted and not entities:
            for turn in reversed(history):
                if turn.role == "user":
                    spotted = await self.linker.spot(turn.content)
                    break
        # The catalog, not the model, decides an entity's type when the text is an exact node name.
        spotted_type = {mention.text.casefold(): mention.type for mention in spotted}
        entities = [
            entity.model_copy(update={"type": spotted_type.get(entity.text.casefold(), entity.type)})
            for entity in entities
        ]
        known_texts = {entity.text.casefold() for entity in entities}
        for mention in spotted:
            if mention.text.casefold() not in known_texts:
                entities.append(mention)
                known_texts.add(mention.text.casefold())

        intent_name = intent.intent
        required_label, needed = REQUIRED_ENTITIES.get(intent_name, ("", 0))
        labels_present = {entity.type for entity in entities}
        if required_label and required_label not in labels_present and "Unknown" not in labels_present:
            for label in ("Paper", "Author", "Institution", "Topic"):
                if label in labels_present:
                    chosen, used = await self.parser.choose_intent(question, label)
                    calls += used
                    if chosen is not None:
                        intent_name = chosen
                        required_label, needed = REQUIRED_ENTITIES.get(chosen, ("", 0))
                    break

        usable = [entity for entity in entities if entity.type in {required_label, "Unknown"}]
        exact = [mention for mention in spotted if mention.type == required_label]
        if exact and len(exact) >= needed:
            usable = exact  # exact catalog names beat model spans such as "Who wrote the paper"
        route = intent.route
        missing = list(intent.missing_fields)
        if len(usable) >= needed:
            route = RouteName.GRAPH_QA
            missing = []
        else:
            route = RouteName.CLARIFY
            missing = missing or [f"{required_label.lower()}_reference"]
        ordered = usable + [entity for entity in entities if entity not in usable]
        repaired = intent.model_copy(
            update={"intent": intent_name, "entities": ordered[:5], "route": route, "missing_fields": missing}
        )
        _ = EntityMention
        return repaired, calls

    async def _loop(self, state: QueryState, first: QueryStep, emit: EmitFn) -> None:
        step: QueryStep | None = first
        decision_source = "rules"
        existing_fact_ids: set[str] = set()
        while step is not None:
            if state.iteration >= state.max_iterations:
                state.stop_reason = "max_iterations"
                return
            if step.fingerprint in state.seen_fingerprints:
                state.stop_reason = "duplicate_step"
                return
            state.seen_fingerprints.add(step.fingerprint)
            await emit(
                "query_start",
                {
                    "iteration": state.iteration + 1,
                    "action": step.action.value,
                    "params": step.params,
                    "decision_source": decision_source,
                },
            )
            started = time.perf_counter()
            try:
                result = await self.repository.execute(step)
                state.db_calls += 1
            except Exception as error:
                state.status = "error"
                state.stop_reason = f"graph_error:{type(error).__name__}"
                state.trace.append(
                    TraceStep(
                        iteration=state.iteration,
                        action=step.action,
                        params=step.params,
                        status="error",
                        detail=type(error).__name__,
                    )
                )
                await emit("error", {"code": "graph_error", "type": type(error).__name__})
                return

            state.iteration += 1
            new_facts = self.normalizer.normalize(result.records)
            delta = [fact for fact in new_facts if fact.fact_id not in existing_fact_ids]
            existing_fact_ids.update(fact.fact_id for fact in delta)
            state.facts.extend(delta)
            state.executed.append(step)
            if result.truncated:
                state.truncated_steps.append(
                    Continuation(
                        action=step.action,
                        params=step.params,
                        offset=step.offset + len(result.records),
                        total=result.total,
                    )
                )
            self._mark_goal_progress(state, step)

            trace = TraceStep(
                iteration=state.iteration,
                action=step.action,
                params=step.params,
                records=len(result.records),
                new_facts=len(delta),
                total=result.total,
                truncated=result.truncated,
                duration_ms=int((time.perf_counter() - started) * 1000),
                status="ok" if result.records else "empty",
                decision_source=decision_source,  # type: ignore[arg-type]
            )
            state.trace.append(trace)
            await emit("query_result", trace.model_dump(mode="json"))

            step, decision, decision_source = await self._decide_next(state, len(delta))
            trace.decision = decision
            await emit(
                "decision",
                {
                    "iteration": state.iteration,
                    "decision": decision,
                    "goals_remaining": state.goals_remaining,
                    "next_action": step.action.value if step else None,
                    "decision_source": decision_source,
                },
            )

    def _mark_goal_progress(self, state: QueryState, step: QueryStep) -> None:
        if state.goals_remaining and state.goals_remaining[0].startswith("main:"):
            state.goals_remaining.pop(0)
        known = self.planner.known_ids(state.linked_entities, state.executed, state.facts)
        # a goal with nothing left to query (all done, or no ID of the needed type) is closed
        state.goals_remaining = [
            goal
            for goal in state.goals_remaining
            if self.planner.pending_for_goal(goal, known, state.seen_fingerprints)
        ]

    async def _decide_next(self, state: QueryState, new_fact_count: int) -> tuple[QueryStep | None, str, str]:
        """Hard rules first (cheap, deterministic); the model only chooses among valid follow-ups."""
        if not state.goals_remaining:
            state.stop_reason = "sufficient"
            return None, "sufficient", "rules"
        if new_fact_count == 0 and len(state.executed) == 1:
            state.stop_reason = "no_progress"
            return None, "no_progress", "rules"
        if state.iteration >= state.max_iterations:
            state.stop_reason = "max_iterations"
            return None, "max_iterations", "rules"

        known = self.planner.known_ids(state.linked_entities, state.executed, state.facts)
        proposal, reason = await self._ask_model(state, known)
        if proposal is not None:
            return proposal, f"continue:{proposal.action.value}", "llm"
        fallback = self.planner.contract_proposal(state.goals_remaining, known, state.seen_fingerprints)
        if fallback is not None:
            return fallback, f"continue:{fallback.action.value} (model:{reason})", "contract_fallback"
        state.stop_reason = "no_valid_next_action"
        return None, f"stop:no_valid_next_action (model:{reason})", "rules"

    async def _ask_model(
        self, state: QueryState, known: dict[str, list[str]]
    ) -> tuple[QueryStep | None, str]:
        compact_facts = [
            {
                "predicate": fact.predicate,
                "subject": fact.subject_id,
                "object": fact.object_id,
                "name": fact.value.get("name") if isinstance(fact.value, dict) else None,
            }
            for fact in state.facts[:20]
        ]
        payload = {
            "QUESTION": state.question,
            "GOALS_REMAINING": state.goals_remaining,
            "OBSERVED_FACTS": compact_facts,
            "KNOWN_IDS": {label: ids[:10] for label, ids in known.items()},
            "EXECUTED": [{"action": step.action.value, "params": step.params} for step in state.executed],
            "ALLOWED_ACTIONS": [
                "paper_venue",
                "paper_authors",
                "paper_citations",
                "author_affiliations",
                "coauthors",
                "author_papers",
            ],
            "REMAINING_BUDGET": state.max_iterations - state.iteration,
        }
        try:
            response = await self.answer_generator.provider.generate(
                [
                    {"role": "system", "content": NEXT_STEP_SYSTEM},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
                ],
                temperature=0,
                max_tokens=300,
                json_mode=True,
            )
            state.llm_calls += 1
            proposal = NextStepProposal.model_validate(json.loads(response.content))
        except (json.JSONDecodeError, ValidationError, ValueError) as error:
            return None, f"invalid_json:{type(error).__name__}"
        except Exception as error:  # provider failure: stop safely, never fabricate
            return None, f"provider_error:{type(error).__name__}"
        if proposal.sufficient or proposal.next_action is None:
            return None, "model_declined"
        step, reason = self.planner.validate_proposal(
            proposal.next_action, proposal.params, known, state.seen_fingerprints
        )
        return step, reason

    @staticmethod
    def _completeness_note(state: QueryState) -> str:
        if not state.truncated_steps:
            return ""
        notes = []
        for item in state.truncated_steps:
            if item.total is not None:
                remaining = max(item.total - item.offset, 0)
                notes.append(
                    f"Đã tìm thấy {item.total} kết quả cho `{item.action.value}`; "
                    f"hiện hiển thị {item.offset} đầu tiên, còn {remaining} kết quả chưa liệt kê "
                    "(bấm “Xem thêm”)."
                )
            else:
                notes.append(
                    f"Kết quả `{item.action.value}` có nhiều hơn {item.offset} dòng; đây chưa phải toàn bộ."
                )
        return "\n".join(notes) + "\n\n"

    async def more(self, request: MoreRequest) -> ChatResponse:
        """Next page of one catalog action. Deterministic listing; no model call."""
        cont = request.continuation
        step = self.planner.step(cont.action, cont.params, offset=cont.offset)
        result = await self.repository.execute(step)
        facts = self.normalizer.normalize(result.records)
        lines = []
        for index, fact in enumerate(facts, start=cont.offset + 1):
            value = fact.value if isinstance(fact.value, dict) else {}
            label = value.get("name") or value.get("title") or fact.object_id
            year = f" ({fact.year})" if fact.year else ""
            lines.append(f"{index}. {label}{year}")
        next_cont = None
        if result.truncated:
            next_cont = Continuation(
                action=cont.action,
                params=cont.params,
                offset=cont.offset + len(result.records),
                total=result.total,
            )
        shown_until = cont.offset + len(result.records)
        header = f"Kết quả {cont.offset + 1}–{shown_until}"
        if result.total is not None:
            header += f" trên tổng {result.total}"
        answer = header + ":\n" + "\n".join(lines) if lines else "Không còn kết quả nào."
        return ChatResponse(
            answer=answer,
            status="partial" if next_cont else "answered",
            route=RouteName.GRAPH_QA,
            complete=next_cont is None,
            iterations_used=1,
            stop_reason="page",
            sources=build_citations(facts),
            facts_count=len(facts),
            provider_info=self._provider_info(),
            continuation=next_cont,
            total_results=result.total,
            shown_results=shown_until,
            db_calls=1,
            watermark=self._watermark(),
        )

    async def _finish(
        self,
        state: QueryState,
        debug: bool,
        ambiguous_candidates: list[CandidateEntity],
        parse_source: str,
        emit: EmitFn,
    ) -> ChatResponse:
        response = self._response(state, debug, ambiguous_candidates, parse_source)
        await emit("answer", {"answer": response.answer})
        return response

    def _response(
        self,
        state: QueryState,
        debug: bool,
        ambiguous_candidates: list[CandidateEntity],
        parse_source: str | None = None,
    ) -> ChatResponse:
        continuation = state.truncated_steps[0] if state.truncated_steps else None
        total = continuation.total if continuation else None
        shown = continuation.offset if continuation else None
        return ChatResponse(
            answer=state.answer,
            status=state.status,  # type: ignore[arg-type]
            route=state.route,
            complete=state.status == "answered" and not state.truncated_steps,
            iterations_used=state.iteration,
            stop_reason=state.stop_reason or "unknown",
            sources=state.sources,
            facts_count=len(state.facts),
            trace=state.trace if debug and self.settings.debug_traces else None,
            provider_info=self._provider_info(),
            ambiguous_candidates=ambiguous_candidates,
            continuation=continuation,
            total_results=total,
            shown_results=shown,
            llm_calls=state.llm_calls,
            db_calls=state.db_calls,
            parse_source=parse_source,
            watermark=self._watermark(),
        )

    def _provider_info(self) -> dict[str, str]:
        info = {
            "mode": self.settings.app_mode,
            "llm": self.settings.llm_provider,
            "graph": self.settings.graph_provider,
        }
        if self.settings.llm_provider == "ollama":
            info["model"] = self.settings.ollama_model
        return info

    def _watermark(self) -> str | None:
        if self.settings.app_mode == "fake":
            return "SIMULATED — no real LLM/DB"
        if self.settings.app_mode == "snapshot":
            return "LOCAL SNAPSHOT — real LLM, offline JSONL graph (not AuraDB)"
        return None

    def _error_response(self, reason: str, debug: bool) -> ChatResponse:
        return ChatResponse(
            answer="Không thể xử lý câu hỏi do lỗi đầu vào mô hình. Không có kết quả giả được thay thế.",
            status="error",
            complete=False,
            iterations_used=0,
            stop_reason=reason,
            facts_count=0,
            trace=[] if debug else None,
            provider_info=self._provider_info(),
            watermark=self._watermark(),
        )
