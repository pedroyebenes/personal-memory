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
DEFAULT_SYNTHESIS_MODEL_NAME = "gpt-5-mini"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"


@dataclass(slots=True)
class Settings:
    vault_path: Path | None = None
    database_path: Path = DEFAULT_DATABASE_PATH
    embedding_model_name: str = DEFAULT_EMBEDDING_MODEL_NAME
    top_k: int = DEFAULT_TOP_K
    enable_llm_synthesis: bool = DEFAULT_ENABLE_LLM_SYNTHESIS
    synthesis_model_name: str | None = DEFAULT_SYNTHESIS_MODEL_NAME
    openai_api_key: str | None = None
    openai_base_url: str = DEFAULT_OPENAI_BASE_URL


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
    synthesis_value = os.getenv("SYNTHESIS_MODEL_NAME", file_values.get("SYNTHESIS_MODEL_NAME"))
    openai_api_key = os.getenv("OPENAI_API_KEY", file_values.get("OPENAI_API_KEY"))
    openai_base_url = os.getenv("OPENAI_BASE_URL", file_values.get("OPENAI_BASE_URL"))

    return Settings(
        vault_path=Path(vault_value).expanduser().resolve() if vault_value else None,
        database_path=Path(db_value).expanduser() if db_value else DEFAULT_DATABASE_PATH,
        embedding_model_name=model_value or DEFAULT_EMBEDDING_MODEL_NAME,
        top_k=int(top_k_value) if top_k_value is not None else DEFAULT_TOP_K,
        enable_llm_synthesis=_parse_bool(enable_value, DEFAULT_ENABLE_LLM_SYNTHESIS),
        synthesis_model_name=synthesis_value or DEFAULT_SYNTHESIS_MODEL_NAME,
        openai_api_key=openai_api_key,
        openai_base_url=openai_base_url or DEFAULT_OPENAI_BASE_URL,
    )
