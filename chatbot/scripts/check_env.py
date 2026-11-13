"""Report profile readiness without printing any secret value."""

from __future__ import annotations

import json
import os
import shutil
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def presence(name: str, required: bool) -> dict[str, str]:
    configured = bool(os.environ.get(name))
    if configured:
        status = "configured"
    elif required:
        status = "missing"
    else:
        status = "optional"
    return {"name": name, "status": status}


def tcp_status(url: str, default_port: int) -> str:
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or default_port
    if not host:
        return "unreachable"
    try:
        with socket.create_connection((host, port), timeout=2):
            return "configured"
    except OSError:
        return "unreachable"


def main() -> int:
    load_dotenv(ROOT / ".env", override=False)
    mode = os.environ.get("APP_MODE", "fake")
    graph = os.environ.get("GRAPH_PROVIDER", "fake")
    llm = os.environ.get("LLM_PROVIDER", "fake")
    real = mode == "real"
    checks: list[dict[str, str]] = [
        {"name": "python", "status": "configured", "detail": sys.version.split()[0]},
        {"name": "uv", "status": "configured" if shutil.which("uv") else "missing"},
        {"name": "node", "status": "configured" if shutil.which("node") else "missing"},
        {"name": "npm", "status": "configured" if shutil.which("npm") else "missing"},
        {"name": "profile", "status": "configured", "detail": f"{mode}/{graph}/{llm}"},
    ]
    for name in ["NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"]:
        checks.append(presence(name, required=real and graph == "neo4j"))
    checks.append(presence("MODEL_ADAPTER_PATH", required=real and llm == "hf_cpu"))
    checks.append(presence("HUGGING_FACE_TOKEN", required=False))
    checks.append(presence("LANGSMITH_API_KEY", required=False))

    if llm == "ollama":
        base_url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        checks.append({"name": "ollama_service", "status": tcp_status(base_url, 11434)})
    else:
        checks.append({"name": "ollama_service", "status": "optional"})

    print(json.dumps({"checks": checks}, indent=2))
    blocking = [check for check in checks if check["status"] in {"missing", "unreachable"}]
    if mode == "fake":
        blocking = [check for check in blocking if check["name"] in {"python", "uv", "node", "npm"}]
    return 1 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
