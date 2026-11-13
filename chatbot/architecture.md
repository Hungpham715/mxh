# Graph-only chatbot architecture

```text
React/Vite UI
  -> FastAPI POST /api/chat or POST SSE /api/chat/stream
  -> IntentParser (fake / Ollama Qwen3 / HF CPU Qwen3)
  -> EntityLinker (exact ID/name, then in-memory RapidFuzz catalog)
  -> Planner (validated intent -> QueryStep whitelist)
  -> GraphRepository (synthetic fixture or Neo4j execute_read)
  -> EvidenceNormalizer (stable fact IDs, paper proof, URL validation)
  -> bounded workflow (delta before merge, fingerprint, max five queries)
  -> GroundedAnswerGenerator
  -> server-owned citations and trace
```

One query execution is one iteration. Entity-catalog loading, health checks, parsing, and answer generation are
not retrieval iterations. A coauthor path up to four edges remains one query iteration. The model never emits
Cypher: it may emit only a validated intent/arguments object, and Python chooses a developer-owned template.

## Boundaries

- `llm/`: three substitutable providers. Real failures remain errors; there is no silent fake fallback.
- `graph/`: repository boundary isolates synthetic tests from Neo4j sessions and resource lifecycle.
- `cypher_templates.py`: twelve parameterized, scope-filtered read-only queries.
- `workflow.py`: explicit state machine rather than LangGraph/agents/tool calling.
- `evidence.py`: facts and citations are derived from graph records, never model prose.

The repository and provider boundaries are industry-standard dependency boundaries. FastAPI lifespan and Pydantic
request validation are framework conventions. The bounded state machine, action fingerprint, and paper-evidence
intersection are custom project choices needed by this graph's semantics. They add some code, but keep query
authority and stopping rules reviewable.

