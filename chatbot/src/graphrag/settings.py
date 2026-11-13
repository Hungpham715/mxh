"""Environment-backed configuration with explicit fake/real profile validation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator


class Settings(BaseModel):
    app_mode: Literal["fake", "real"] = "fake"
    graph_provider: Literal["fake", "neo4j"] = "fake"
    llm_provider: Literal["fake", "ollama", "hf_cpu"] = "fake"
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    web_port: int = Field(default=5173, ge=1, le=65535)
    frontend_origin: str = "http://localhost:5173"
    max_iterations: int = Field(default=5, ge=1, le=5)
    max_records_per_query: int = Field(default=20, ge=1, le=100)
    max_graph_hops: int = Field(default=4, ge=1, le=4)
    request_timeout_seconds: float = Field(default=120, gt=0, le=300)
    ollama_timeout_seconds: float = Field(default=120, gt=0, le=300)
    entity_cache_ttl_seconds: int = Field(default=900, ge=30)
    fuzzy_score_threshold: float = Field(default=90, ge=0, le=100)
    fuzzy_score_margin: float = Field(default=8, ge=0, le=100)
    debug_traces: bool = True
    enable_sse: bool = True
    log_level: str = "INFO"
    neo4j_uri: str | None = None
    neo4j_username: str | None = None
    neo4j_password: str | None = None
    neo4j_database: str = "neo4j"
    neo4j_scope_id: str = "nlpgraph-v1"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:0.6b"
    hf_model_id: str = "Qwen/Qwen3-0.6B"
    model_adapter_path: str | None = None
    device: Literal["cpu"] = "cpu"
    use_adapter: bool = False
    dataset_root: Path = Path("data")
    eval_output_dir: Path = Path("reports/eval")

    @model_validator(mode="after")
    def validate_profile(self) -> Settings:
        if self.app_mode == "fake":
            if self.graph_provider != "fake" or self.llm_provider != "fake":
                raise ValueError("APP_MODE=fake requires GRAPH_PROVIDER=fake and LLM_PROVIDER=fake")
            return self

        if self.graph_provider != "neo4j":
            raise ValueError("APP_MODE=real requires GRAPH_PROVIDER=neo4j")
        if self.llm_provider == "fake":
            raise ValueError("APP_MODE=real never falls back to the fake LLM")
        if not all((self.neo4j_uri, self.neo4j_username, self.neo4j_password)):
            raise ValueError("real mode requires NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD")
        if self.llm_provider == "hf_cpu" and self.use_adapter and not self.model_adapter_path:
            raise ValueError("USE_ADAPTER=true requires MODEL_ADAPTER_PATH")
        return self

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> Settings:
        if env_file is None:
            env_file = Path(__file__).resolve().parents[2] / ".env"
        load_dotenv(env_file, override=False)

        values: dict[str, object] = {}
        for field_name in cls.model_fields:
            env_name = field_name.upper()
            if env_name in os.environ:
                values[field_name] = os.environ[env_name]
        return cls.model_validate(values)

    def public_dict(self) -> dict[str, object]:
        return {
            "mode": self.app_mode,
            "graph_provider": self.graph_provider,
            "llm_provider": self.llm_provider,
            "scope_id": self.neo4j_scope_id,
            "max_iterations": self.max_iterations,
            "max_records_per_query": self.max_records_per_query,
            "max_graph_hops": self.max_graph_hops,
            "debug_traces": self.debug_traces,
            "enable_sse": self.enable_sse,
        }
