"""Shared helpers: paths, env, JSONL IO, polite cached HTTP with retry, secret scrubbing."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Iterable, Iterator

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
CACHE = DATA / "cache"
PROCESSED = DATA / "processed"
REJECTED = DATA / "rejected"
DERIVED = DATA / "derived"
FIXTURES = DATA / "fixtures"
OUTPUT = ROOT / "output"
EVAL = ROOT / "evaluation"

SCOPE_ID = "nlpgraph-v1"
BUILD_VERSION = "1.0.0"

log = logging.getLogger("nlpgraph")


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("neo4j").setLevel(logging.WARNING)
    logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)


def load_env() -> None:
    load_dotenv(ROOT / ".env", override=False)


def env(name: str, *fallbacks: str, default: str | None = None) -> str | None:
    for key in (name, *fallbacks):
        val = os.environ.get(key)
        if val:
            return val
    return default


_SECRET_ENV = ("NEO4J_PASSWORD", "OPENALEX_API_KEY")


def scrub(text: str) -> str:
    """Remove secret values and api_key query params from any string before logging."""
    text = re.sub(r"(api_key=)[^&\s'\"]+", r"\1***", str(text))
    for key in _SECRET_ENV:
        val = os.environ.get(key)
        if val and len(val) >= 4:
            text = text.replace(val, "***")
    return text


# ---------------------------------------------------------------- JSONL
def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name}:{n}: invalid JSON ({exc})") from exc
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=False) + "\n")
            n += 1
    return n


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def read_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- HTTP
class HttpError(RuntimeError):
    pass


class CachedClient:
    """Polite HTTP GET with on-disk cache, bounded retry/backoff for 429/5xx/timeouts, request log."""

    def __init__(self, namespace: str, min_interval: float = 0.0, timeout: float = 60.0,
                 max_retries: int = 6, extra_params: dict[str, str] | None = None):
        contact = env("CONTACT_EMAIL") or "student-project"
        self.client = httpx.Client(
            timeout=timeout, follow_redirects=True,
            headers={"User-Agent": f"nlp-collab-graph/1.0 (academic course project; contact: {contact})"},
        )
        self.cache_dir = CACHE / namespace
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = RAW / f"{namespace}_requests.jsonl"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.extra_params = extra_params or {}  # e.g. api_key; never part of cache key or log
        self._last = 0.0

    def _key(self, url: str, params: dict[str, Any] | None) -> Path:
        raw = url + "?" + json.dumps(params or {}, sort_keys=True)
        return self.cache_dir / (hashlib.sha256(raw.encode()).hexdigest()[:32] + ".body")

    def _log(self, rec: dict[str, Any]) -> None:
        with open(self.log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def get(self, url: str, params: dict[str, Any] | None = None, allow_404: bool = False) -> str | None:
        path = self._key(url, params)
        if path.exists():
            body = path.read_text(encoding="utf-8")
            return None if body == "__404__" else body
        delay = 2.0
        status: Any = None
        resp: httpx.Response | None = None
        for attempt in range(1, self.max_retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            status: Any = None
            try:
                resp = self.client.get(url, params={**(params or {}), **self.extra_params})
                status = resp.status_code
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                status = f"transport:{type(exc).__name__}"
            ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self._log({"ts": ts, "url": scrub(url), "params": params, "status": status, "attempt": attempt})
            if status == 200:
                body = resp.text
                path.write_text(body, encoding="utf-8")
                return body
            if status == 404 and allow_404:
                path.write_text("__404__", encoding="utf-8")
                return None
            if status == 429 or (isinstance(status, int) and status >= 500) or isinstance(status, str):
                retry_after = None
                if status == 429:
                    try:
                        retry_after = float(resp.headers.get("Retry-After", ""))
                    except ValueError:
                        retry_after = None
                time.sleep(min(retry_after or delay, 120))
                delay *= 2
                continue
            raise HttpError(scrub(f"GET {url} -> HTTP {status}"))
        raise HttpError(scrub(f"GET {url} failed after {self.max_retries} attempts (last status {status})"))
