from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_DATABASE_PATH = Path("data/cache/memory.sqlite3")
DEFAULT_EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_TOP_K = 5
DEFAULT_ENABLE_LLM_SYNTHESIS = False
DEFAULT_ENABLE_QUERY_REWRITE = False
DEFAULT_LLM_PROVIDER = "ollama"
DEFAULT_SYNTHESIS_MODEL_NAME = "gemma3"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/api"


@dataclass(slots=True)
class Settings:
    vault_path: Path | None = None
    database_path: Path = DEFAULT_DATABASE_PATH
    embedding_model_name: str = DEFAULT_EMBEDDING_MODEL_NAME
    top_k: int = DEFAULT_TOP_K
    enable_llm_synthesis: bool = DEFAULT_ENABLE_LLM_SYNTHESIS
    enable_query_rewrite: bool = DEFAULT_ENABLE_QUERY_REWRITE
    llm_provider: str = DEFAULT_LLM_PROVIDER
    synthesis_model_name: str | None = DEFAULT_SYNTHESIS_MODEL_NAME
    openai_api_key: str | None = None
    openai_base_url: str = DEFAULT_OPENAI_BASE_URL
    gemini_api_key: str | None = None
    gemini_base_url: str = DEFAULT_GEMINI_BASE_URL
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _load_config_file(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_settings(config_path: str | None = None) -> Settings:
    file_path = Path(config_path) if config_path else Path("config.json")
    file_values = _load_config_file(file_path if file_path.exists() else None)

    vault_value = os.getenv("VAULT_PATH", file_values.get("VAULT_PATH"))
    db_value = os.getenv("DATABASE_PATH", file_values.get("DATABASE_PATH"))
    model_value = os.getenv("EMBEDDING_MODEL_NAME", file_values.get("EMBEDDING_MODEL_NAME"))
    top_k_value = os.getenv("TOP_K", file_values.get("TOP_K"))
    enable_value = os.getenv("ENABLE_LLM_SYNTHESIS", file_values.get("ENABLE_LLM_SYNTHESIS"))
    rewrite_value = os.getenv("ENABLE_QUERY_REWRITE", file_values.get("ENABLE_QUERY_REWRITE"))
    provider_value = os.getenv("LLM_PROVIDER", file_values.get("LLM_PROVIDER"))
    synthesis_value = os.getenv("SYNTHESIS_MODEL_NAME", file_values.get("SYNTHESIS_MODEL_NAME"))
    openai_api_key = os.getenv("OPENAI_API_KEY", file_values.get("OPENAI_API_KEY"))
    openai_base_url = os.getenv("OPENAI_BASE_URL", file_values.get("OPENAI_BASE_URL"))
    gemini_api_key = os.getenv("GEMINI_API_KEY", file_values.get("GEMINI_API_KEY"))
    gemini_base_url = os.getenv("GEMINI_BASE_URL", file_values.get("GEMINI_BASE_URL"))
    ollama_base_url = os.getenv("OLLAMA_BASE_URL", file_values.get("OLLAMA_BASE_URL"))

    return Settings(
        vault_path=Path(vault_value).expanduser().resolve() if vault_value else None,
        database_path=Path(db_value).expanduser() if db_value else DEFAULT_DATABASE_PATH,
        embedding_model_name=model_value or DEFAULT_EMBEDDING_MODEL_NAME,
        top_k=int(top_k_value) if top_k_value is not None else DEFAULT_TOP_K,
        enable_llm_synthesis=_parse_bool(enable_value, DEFAULT_ENABLE_LLM_SYNTHESIS),
        enable_query_rewrite=_parse_bool(rewrite_value, DEFAULT_ENABLE_QUERY_REWRITE),
        llm_provider=(provider_value or DEFAULT_LLM_PROVIDER).strip().lower(),
        synthesis_model_name=synthesis_value or DEFAULT_SYNTHESIS_MODEL_NAME,
        openai_api_key=openai_api_key,
        openai_base_url=openai_base_url or DEFAULT_OPENAI_BASE_URL,
        gemini_api_key=gemini_api_key,
        gemini_base_url=gemini_base_url or DEFAULT_GEMINI_BASE_URL,
        ollama_base_url=ollama_base_url or DEFAULT_OLLAMA_BASE_URL,
    )
