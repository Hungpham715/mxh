"""Reproducible REAL API/SSE smoke; writes no credentials."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx

BASE_URL = "http://127.0.0.1:8000"
OUTPUT_NAME = os.environ.get("API_SMOKE_OUTPUT", "api_real_smoke.json")
if Path(OUTPUT_NAME).name != OUTPUT_NAME:
    raise ValueError("API_SMOKE_OUTPUT must be a plain filename")
OUTPUT = Path(__file__).with_name(OUTPUT_NAME)
PAYLOAD = {
    "question": "Các bài báo của tác giả Xipeng Qiu trong tập dữ liệu?",
    "history": [],
    "debug": True,
}


def matrix_cases() -> list[dict]:
    entities = json.loads(Path(__file__).with_name("live_entities.json").read_text(encoding="utf-8"))
    return [
        {
            "id": "affiliation",
            "payload": {
                "question": (f"{entities['affil_author'][0]['author']} gắn với tổ chức nào theo các bài báo?")
            },
            "statuses": {"answered"},
            "intent": "author_affiliations",
        },
        {
            "id": "paper_authors",
            "payload": {"question": f"Ai là tác giả của bài {entities['venue_paper'][0]['title']}?"},
            "statuses": {"answered"},
            "intent": "paper_authors",
        },
        {
            "id": "organization",
            "payload": {
                "question": f"{entities['top_org'][0]['name']} hợp tác với tổ chức nào trong corpus?"
            },
            # top collaborator org exceeds the 20-row default page: truncated -> partial is the
            # intended contract, so partial must be accepted alongside answered.
            "statuses": {"answered", "partial"},
            "intent": "org_collaborations",
        },
        {
            "id": "unknown_entity",
            "payload": {"question": 'Bài báo của tác giả "Nguyen Van Khong Co That"'},
            "statuses": {"not_found", "out_of_scope", "clarify"},
            "intent": None,
        },
        {
            "id": "missing_reference",
            "payload": {"question": "Các bài báo của tác giả đó?"},
            "statuses": {"not_found", "clarify"},
            "intent": None,
        },
        {
            "id": "out_of_scope",
            "payload": {"question": "Đặt phòng họp ngày mai lúc 8 giờ"},
            "statuses": {"out_of_scope"},
            "intent": None,
        },
        {
            "id": "chat_history",
            "payload": {
                "question": "Câu hỏi đầu tiên tôi hỏi bạn là gì?",
                "history": [
                    {"role": "user", "content": "Các bài báo của Xipeng Qiu?"},
                    {"role": "assistant", "content": "Đã tìm thấy các bài báo."},
                ],
            },
            "statuses": {"answered"},
            "intent": None,
        },
        {
            "id": "ambiguous_name",
            "payload": {"question": f"Các bài báo của tác giả {entities['ambiguous_names'][0]['name']}?"},
            "statuses": {"ambiguous", "answered"},
            "intent": "author_papers",
        },
    ]


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
        matrix: list[dict] = []
        for case in matrix_cases():
            response = client.post(f"{BASE_URL}/api/chat", json=case["payload"])
            response.raise_for_status()
            projection = semantic_projection(response.json())
            case_pass = projection["status"] in case["statuses"]
            if case["intent"] is not None:
                case_pass = case_pass and projection["parsed_intent"] == case["intent"]
            matrix.append({"id": case["id"], **projection, "pass": case_pass})
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
        "target": os.environ.get(
            "API_SMOKE_TARGET", "local Neo4j Community snapshot + Ollama qwen3:0.6b (NOT Aura)"
        ),
        "health": health.json(),
        "event_names": [event["name"] for event in events],
        "regular": regular_semantics,
        "stream": stream_semantics,
        "matrix": matrix,
        "matrix_passed": sum(row["pass"] for row in matrix),
        "matrix_total": len(matrix),
        "semantic_match": regular_semantics == stream_semantics,
        "pass": (
            regular_semantics == stream_semantics
            and regular_semantics["status"] == "answered"
            and regular_semantics["parsed_intent"] == "author_papers"
            and all(row["pass"] for row in matrix)
        ),
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["pass"] else 1)


if __name__ == "__main__":
    main()
