"""Reproducible local REAL API/SSE smoke; writes no credentials."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

BASE_URL = "http://127.0.0.1:8000"
OUTPUT = Path(__file__).with_name("api_real_smoke.json")
PAYLOAD = {
    "question": "Các bài báo của tác giả Xipeng Qiu trong tập dữ liệu?",
    "history": [],
    "debug": True,
}


def semantic_projection(response: dict) -> dict:
    return {
        "status": response.get("status"),
        "route": response.get("route"),
        "parsed_intent": response.get("parsed_intent"),
        "facts_count": response.get("facts_count"),
        "source_paper_ids": sorted(source["paper_id"] for source in response.get("sources", [])),
    }


def main() -> None:
    with httpx.Client(timeout=180) as client:
        health = client.get(f"{BASE_URL}/api/health")
        health.raise_for_status()
        regular = client.post(f"{BASE_URL}/api/chat", json=PAYLOAD)
        regular.raise_for_status()

        events: list[dict] = []
        event_name: str | None = None
        with client.stream("POST", f"{BASE_URL}/api/chat/stream", json=PAYLOAD) as streamed:
            streamed.raise_for_status()
            for line in streamed.iter_lines():
                if line.startswith("event: "):
                    event_name = line.removeprefix("event: ")
                elif line.startswith("data: "):
                    events.append(
                        {
                            "name": event_name,
                            "data": json.loads(line.removeprefix("data: ")),
                        }
                    )

    done = next(event["data"] for event in events if event["name"] == "done")
    regular_json = regular.json()
    regular_semantics = semantic_projection(regular_json)
    stream_semantics = semantic_projection(done)
    report = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "target": "local Neo4j Community snapshot + Ollama qwen3:0.6b (NOT Aura)",
        "health": health.json(),
        "event_names": [event["name"] for event in events],
        "regular": regular_semantics,
        "stream": stream_semantics,
        "semantic_match": regular_semantics == stream_semantics,
        "pass": (
            regular_semantics == stream_semantics
            and regular_semantics["status"] == "answered"
            and regular_semantics["parsed_intent"] == "author_papers"
        ),
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["pass"] else 1)


if __name__ == "__main__":
    main()
