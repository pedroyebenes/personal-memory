from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SUPPORTED_LLM_PROVIDERS = ("ollama", "openai", "gemini", "nvidia")
DEFAULT_DATABASE_PATH = Path("data/cache/memory.sqlite3")
DEFAULT_CONFIG_PATH = Path("config.json")
DEFAULT_EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_TOP_K = 5
DEFAULT_ENABLE_LLM_SYNTHESIS = False
DEFAULT_ENABLE_QUERY_REWRITE = False
DEFAULT_LLM_PROVIDER = "ollama"
DEFAULT_SYNTHESIS_MODEL_NAME = "gemma3"
DEFAULT_OPENAI_SYNTHESIS_MODEL_NAME = "gpt-5-mini"
DEFAULT_GEMINI_SYNTHESIS_MODEL_NAME = "gemini-2.5-flash"
DEFAULT_NVIDIA_SYNTHESIS_MODEL_NAME = "minimaxai/minimax-m2.7"
DEFAULT_OLLAMA_SYNTHESIS_MODEL_NAME = "gemma3"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
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
    synthesis_model_name: str | None = None
    openai_synthesis_model_name: str = DEFAULT_OPENAI_SYNTHESIS_MODEL_NAME
    gemini_synthesis_model_name: str = DEFAULT_GEMINI_SYNTHESIS_MODEL_NAME
    nvidia_synthesis_model_name: str = DEFAULT_NVIDIA_SYNTHESIS_MODEL_NAME
    ollama_synthesis_model_name: str = DEFAULT_OLLAMA_SYNTHESIS_MODEL_NAME
    openai_api_key: str | None = None
    openai_base_url: str = DEFAULT_OPENAI_BASE_URL
    gemini_api_key: str | None = None
    gemini_base_url: str = DEFAULT_GEMINI_BASE_URL
    nvidia_api_key: str | None = None
    nvidia_base_url: str = DEFAULT_NVIDIA_BASE_URL
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL

    def is_supported_provider(self, provider: str | None = None) -> bool:
        provider_name = (provider or self.llm_provider).strip().lower()
        return provider_name in SUPPORTED_LLM_PROVIDERS

    def get_synthesis_model_name(self, provider: str | None = None) -> str | None:
        if self.synthesis_model_name:
            return self.synthesis_model_name
        provider_name = (provider or self.llm_provider).strip().lower()
        if provider_name == "openai":
            return self.openai_synthesis_model_name
        if provider_name == "gemini":
            return self.gemini_synthesis_model_name
        if provider_name == "nvidia":
            return self.nvidia_synthesis_model_name
        if provider_name == "ollama":
            return self.ollama_synthesis_model_name
        return None

    def synthesis_model_defaults(self) -> dict[str, str]:
        return {
            "openai": self.openai_synthesis_model_name,
            "gemini": self.gemini_synthesis_model_name,
            "nvidia": self.nvidia_synthesis_model_name,
            "ollama": self.ollama_synthesis_model_name,
        }

    def provider_availability(self) -> dict[str, dict[str, str | bool]]:
        availability = {
            "ollama": {"available": True, "reason": ""},
            "openai": {
                "available": bool(self.openai_api_key),
                "reason": "" if self.openai_api_key else "OPENAI_API_KEY is not configured.",
            },
            "gemini": {
                "available": bool(self.gemini_api_key),
                "reason": "" if self.gemini_api_key else "GEMINI_API_KEY is not configured.",
            },
            "nvidia": {
                "available": bool(self.nvidia_api_key),
                "reason": "" if self.nvidia_api_key else "NVIDIA_API_KEY is not configured.",
            },
        }
        if not self.is_supported_provider():
            availability[self.llm_provider] = {
                "available": False,
                "reason": f"Unsupported LLM_PROVIDER: {self.llm_provider}",
            }
        return availability

    def validate(self) -> list[dict[str, str]]:
        diagnostics: list[dict[str, str]] = []
        if not self.is_supported_provider():
            diagnostics.append(
                {
                    "code": "unsupported_provider",
                    "field": "LLM_PROVIDER",
                    "message": f"Unsupported LLM_PROVIDER: {self.llm_provider}",
                }
            )
        if self.vault_path is not None:
            if not self.vault_path.exists():
                diagnostics.append(
                    {
                        "code": "vault_not_found",
                        "field": "VAULT_PATH",
                        "message": f"VAULT_PATH does not exist: {self.vault_path}",
                    }
                )
            elif not self.vault_path.is_dir():
                diagnostics.append(
                    {
                        "code": "vault_not_directory",
                        "field": "VAULT_PATH",
                        "message": f"VAULT_PATH is not a directory: {self.vault_path}",
                    }
                )
        if self.database_path.exists() and not self.database_path.is_file():
            diagnostics.append(
                {
                    "code": "database_not_file",
                    "field": "DATABASE_PATH",
                    "message": f"DATABASE_PATH is not a file: {self.database_path}",
                }
            )
        elif self.database_path.parent.exists() and not self.database_path.parent.is_dir():
            diagnostics.append(
                {
                    "code": "database_parent_not_directory",
                    "field": "DATABASE_PATH",
                    "message": f"DATABASE_PATH parent is not a directory: {self.database_path.parent}",
                }
            )
        return diagnostics


def _parse_bool(value: bool | str | None, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _load_config_file(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _coerce_path(value: str | None, *, base_dir: Path | None = None, resolve: bool = False) -> Path | None:
    if value is None:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute() and base_dir is not None:
        path = base_dir / path
    return path.resolve() if resolve else path


def load_settings(config_path: str | None = None) -> Settings:
    file_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    file_values = _load_config_file(file_path if file_path.exists() else None)
    config_dir = file_path.resolve().parent if file_path.exists() else None

    model_value = os.getenv("EMBEDDING_MODEL_NAME", file_values.get("EMBEDDING_MODEL_NAME"))
    top_k_value = os.getenv("TOP_K", file_values.get("TOP_K"))
    enable_value = os.getenv("ENABLE_LLM_SYNTHESIS", file_values.get("ENABLE_LLM_SYNTHESIS"))
    rewrite_value = os.getenv("ENABLE_QUERY_REWRITE", file_values.get("ENABLE_QUERY_REWRITE"))
    provider_value = os.getenv("LLM_PROVIDER", file_values.get("LLM_PROVIDER"))
    synthesis_value = os.getenv("SYNTHESIS_MODEL_NAME", file_values.get("SYNTHESIS_MODEL_NAME"))
    openai_synthesis_value = os.getenv("OPENAI_SYNTHESIS_MODEL_NAME", file_values.get("OPENAI_SYNTHESIS_MODEL_NAME"))
    gemini_synthesis_value = os.getenv("GEMINI_SYNTHESIS_MODEL_NAME", file_values.get("GEMINI_SYNTHESIS_MODEL_NAME"))
    nvidia_synthesis_value = os.getenv("NVIDIA_SYNTHESIS_MODEL_NAME", file_values.get("NVIDIA_SYNTHESIS_MODEL_NAME"))
    ollama_synthesis_value = os.getenv("OLLAMA_SYNTHESIS_MODEL_NAME", file_values.get("OLLAMA_SYNTHESIS_MODEL_NAME"))
    openai_api_key = os.getenv("OPENAI_API_KEY", file_values.get("OPENAI_API_KEY"))
    openai_base_url = os.getenv("OPENAI_BASE_URL", file_values.get("OPENAI_BASE_URL"))
    gemini_api_key = os.getenv("GEMINI_API_KEY", file_values.get("GEMINI_API_KEY"))
    gemini_base_url = os.getenv("GEMINI_BASE_URL", file_values.get("GEMINI_BASE_URL"))
    nvidia_api_key = os.getenv("NVIDIA_API_KEY", file_values.get("NVIDIA_API_KEY"))
    nvidia_base_url = os.getenv("NVIDIA_BASE_URL", file_values.get("NVIDIA_BASE_URL"))
    ollama_base_url = os.getenv("OLLAMA_BASE_URL", file_values.get("OLLAMA_BASE_URL"))

    vault_path = _coerce_path(os.getenv("VAULT_PATH"), resolve=True)
    if vault_path is None:
        vault_path = _coerce_path(file_values.get("VAULT_PATH"), base_dir=config_dir, resolve=True)

    database_path = _coerce_path(os.getenv("DATABASE_PATH"))
    if database_path is None:
        database_path = _coerce_path(file_values.get("DATABASE_PATH"), base_dir=config_dir)

    return Settings(
        vault_path=vault_path,
        database_path=database_path or DEFAULT_DATABASE_PATH,
        embedding_model_name=model_value or DEFAULT_EMBEDDING_MODEL_NAME,
        top_k=int(top_k_value) if top_k_value is not None else DEFAULT_TOP_K,
        enable_llm_synthesis=_parse_bool(enable_value, DEFAULT_ENABLE_LLM_SYNTHESIS),
        enable_query_rewrite=_parse_bool(rewrite_value, DEFAULT_ENABLE_QUERY_REWRITE),
        llm_provider=(provider_value or DEFAULT_LLM_PROVIDER).strip().lower(),
        synthesis_model_name=synthesis_value,
        openai_synthesis_model_name=openai_synthesis_value or DEFAULT_OPENAI_SYNTHESIS_MODEL_NAME,
        gemini_synthesis_model_name=gemini_synthesis_value or DEFAULT_GEMINI_SYNTHESIS_MODEL_NAME,
        nvidia_synthesis_model_name=nvidia_synthesis_value or DEFAULT_NVIDIA_SYNTHESIS_MODEL_NAME,
        ollama_synthesis_model_name=ollama_synthesis_value or synthesis_value or DEFAULT_OLLAMA_SYNTHESIS_MODEL_NAME,
        openai_api_key=openai_api_key,
        openai_base_url=openai_base_url or DEFAULT_OPENAI_BASE_URL,
        gemini_api_key=gemini_api_key,
        gemini_base_url=gemini_base_url or DEFAULT_GEMINI_BASE_URL,
        nvidia_api_key=nvidia_api_key,
        nvidia_base_url=nvidia_base_url or DEFAULT_NVIDIA_BASE_URL,
        ollama_base_url=ollama_base_url or DEFAULT_OLLAMA_BASE_URL,
    )
