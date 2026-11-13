"""Run real questions through the graph-only RAG workflow and print grounded answers.

Read-only against the configured graph. The profile comes from chatbot/.env; override it with
environment variables without editing the file (Settings uses load_dotenv(override=False)), e.g.:

    LLM_PROVIDER=hf_cpu USE_ADAPTER=true \
    MODEL_ADAPTER_PATH=data/models/qwen3-06b-graphrag-lora \
    uv run python scripts/ask.py --from-test 5

Real-provider failures are surfaced explicitly; no fake answer is substituted.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from graphrag.factory import build_dependencies
from graphrag.models import ChatRequest
from graphrag.settings import Settings


def load_test_questions(count: int, path: Path) -> list[str]:
    """Pull a few answered held-out questions so the demo uses real graph entities."""
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    answered = [row["question"] for row in rows if row.get("expected_status") == "answered"]
    return answered[:count]


async def run(questions: list[str]) -> None:
    settings = Settings.from_env()
    print(
        f"profile: mode={settings.app_mode} graph={settings.graph_provider} "
        f"llm={settings.llm_provider} adapter={settings.use_adapter} "
        f"model={settings.hf_model_id}"
    )
    llm, repository, workflow = build_dependencies(settings)
    try:
        for question in questions:
            response = await workflow.run(ChatRequest(question=question, debug=True))
            print("=" * 90)
            print("Q:", question)
            print(
                f"status={response.status} stop={response.stop_reason} "
                f"iterations={response.iterations_used} facts={response.facts_count} "
                f"llm_calls={response.provider_info}"
            )
            print("A:", response.answer)
            if response.sources:
                print("sources:")
                for source in response.sources[:5]:
                    print(f"  - [{source.paper_id}] {source.title}\n    {source.url}")
            if response.ambiguous_candidates:
                print("ambiguous candidates:")
                for candidate in response.ambiguous_candidates:
                    print(f"  - {candidate.id} | {candidate.name} ({candidate.label})")
            if response.trace:
                print("trace:", [(step.action, step.status, step.records) for step in response.trace])
    finally:
        await repository.close()
        await llm.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("questions", nargs="*", help="questions to ask")
    parser.add_argument(
        "--from-test", type=int, default=0, help="pull N answered questions from the test split"
    )
    parser.add_argument("--test-path", type=Path, default=Path("data/splits/test.jsonl"))
    args = parser.parse_args()

    questions = list(args.questions)
    if args.from_test:
        questions.extend(load_test_questions(args.from_test, args.test_path))
    if not questions:
        raise SystemExit("pass questions positionally or use --from-test N")
    asyncio.run(run(questions))


if __name__ == "__main__":
    main()
