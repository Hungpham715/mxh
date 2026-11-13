"""Build application dependencies at one explicit boundary."""

from __future__ import annotations

from graphrag.answer import GroundedAnswerGenerator
from graphrag.entity_linking import EntityLinker
from graphrag.graph.fake_graph import FakeGraphRepository
from graphrag.graph.neo4j_readonly import Neo4jReadOnlyRepository
from graphrag.intent_parser import IntentParser
from graphrag.llm.fake import FakeLLMProvider
from graphrag.llm.hf_cpu import HFCPUProvider
from graphrag.llm.ollama_cpu import OllamaProvider
from graphrag.planner import Planner
from graphrag.settings import Settings
from graphrag.workflow import GraphRAGWorkflow


def build_dependencies(settings: Settings):
    if settings.llm_provider == "fake":
        llm = FakeLLMProvider()
    elif settings.llm_provider == "ollama":
        llm = OllamaProvider(
            settings.ollama_base_url,
            settings.ollama_model,
            settings.ollama_timeout_seconds,
        )
    else:
        llm = HFCPUProvider(settings.hf_model_id, settings.model_adapter_path, settings.use_adapter)

    if settings.graph_provider == "fake":
        repository = FakeGraphRepository()
    else:
        assert settings.neo4j_uri is not None
        assert settings.neo4j_username is not None
        assert settings.neo4j_password is not None
        repository = Neo4jReadOnlyRepository(
            uri=settings.neo4j_uri,
            username=settings.neo4j_username,
            password=settings.neo4j_password,
            database=settings.neo4j_database,
            scope_id=settings.neo4j_scope_id,
            cache_ttl_seconds=settings.entity_cache_ttl_seconds,
            timeout_seconds=settings.request_timeout_seconds,
        )

    parser = IntentParser(llm)
    linker = EntityLinker(repository, settings.fuzzy_score_threshold, settings.fuzzy_score_margin)
    planner = Planner(settings.max_records_per_query)
    answer_generator = GroundedAnswerGenerator(llm)
    workflow = GraphRAGWorkflow(settings, repository, parser, linker, planner, answer_generator)
    return llm, repository, workflow
