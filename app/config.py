from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SUPPORTED_LLM_PROVIDERS = ("ollama", "openai", "gemini", "nvidia", "mlx_lm")
DEFAULT_DATABASE_PATH = Path("data/cache/memory.sqlite3")
DEFAULT_CONFIG_PATH = Path("config.json")
DEFAULT_EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_TOP_K = 5
DEFAULT_ENABLE_LLM_SYNTHESIS = False
DEFAULT_ENABLE_QUERY_REWRITE = False
DEFAULT_ENABLE_RERANKING = False
DEFAULT_ENABLE_CONCEPT_BOOST = False
DEFAULT_USE_BREADCRUMB_EMBEDDINGS = True
DEFAULT_RETRIEVAL_CANDIDATE_MULTIPLIER = 10
DEFAULT_RETRIEVAL_CANDIDATE_MIN = 50
DEFAULT_RETRIEVAL_CANDIDATE_MAX = 200
DEFAULT_CONCEPT_BOOST_WEIGHT = 0.06
DEFAULT_CONCEPT_BOOST_EXACT_MAX = 0.15
DEFAULT_RERANK_MAX_BOOST = 0.18
DEFAULT_EVIDENCE_SUFFICIENCY_THRESHOLD = 0.2
DEFAULT_SYNTHESIS_MODEL_NAME = "gemma4:e2b"
DEFAULT_OPENAI_SYNTHESIS_MODEL_NAME = "gpt-5-mini"
DEFAULT_GEMINI_SYNTHESIS_MODEL_NAME = "gemini-2.5-flash"
DEFAULT_NVIDIA_SYNTHESIS_MODEL_NAME = "minimaxai/minimax-m2.7"
DEFAULT_OLLAMA_SYNTHESIS_MODEL_NAME = "gemma4:e2b"
DEFAULT_MLX_LM_SYNTHESIS_MODEL_NAME = "mlx-community/gemma-4-e4b-it-8bit"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/api"
DEFAULT_MLX_LM_BASE_URL = "http://localhost:8080/v1"


def normalize_provider_name(provider: str | None) -> str:
    return (provider or "").strip().lower().replace("-", "_")


def supported_llm_providers_list() -> list[str]:
    """Stable list of provider ids the app implements (for API / UI)."""
    return list(SUPPORTED_LLM_PROVIDERS)


def _normalize_nested_provider_key(key: str) -> str | None:
    k = str(key).strip().lower().replace("-", "_")
    if k in ("model", "model_name", "synthesis_model", "synthesis_model_name"):
        return "synthesis_model_name"
    if k in ("api_key", "apikey"):
        return "api_key"
    if k in ("base_url", "baseurl", "url"):
        return "base_url"
    return None


def _flatten_provider_object(obj: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for raw_k, raw_v in obj.items():
        nk = _normalize_nested_provider_key(str(raw_k))
        if nk is None:
            continue
        out[nk] = raw_v
    return out


def provider_blocks_from_config(file_values: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Merge nested provider settings from PROVIDERS / providers and top-level provider dicts (e.g. NVIDIA: {...})."""
    merged: dict[str, dict[str, Any]] = {}

    def merge_into(pid: str, obj: dict[str, Any]) -> None:
        if pid not in SUPPORTED_LLM_PROVIDERS:
            return
        flat = _flatten_provider_object(obj)
        if not flat:
            return
        bucket = merged.setdefault(pid, {})
        bucket.update(flat)

    collective = file_values.get("PROVIDERS") or file_values.get("providers")
    if isinstance(collective, dict):
        for name, obj in collective.items():
            if isinstance(obj, dict):
                merge_into(normalize_provider_name(str(name)), obj)

    for fk, fv in file_values.items():
        if fk in ("PROVIDERS", "providers"):
            continue
        if isinstance(fv, dict):
            pid = normalize_provider_name(str(fk))
            if pid in SUPPORTED_LLM_PROVIDERS:
                merge_into(pid, fv)

    return merged


def _env_nonempty(name: str) -> str | None:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return None
    return str(raw).strip()


def _pick_provider_setting(
    env_name: str,
    nested: dict[str, dict[str, Any]],
    pid: str,
    nested_field: str,
    flat_file_key: str,
    file_values: dict[str, Any],
) -> str | None:
    ev = _env_nonempty(env_name)
    if ev is not None:
        return ev
    block = nested.get(pid) or {}
    nv = block.get(nested_field)
    if nv is not None and str(nv).strip() != "":
        return str(nv).strip()
    fv = file_values.get(flat_file_key)
    if fv is not None and str(fv).strip() != "":
        return str(fv).strip()
    return None


def _parse_provider_order(value: Any) -> tuple[str, ...]:
    """Parse LLM_PROVIDER_ORDER from JSON (array), comma-separated string, or env."""
    if value is None:
        return ()
    if isinstance(value, str):
        items = [normalize_provider_name(part) for part in value.split(",") if part.strip()]
    elif isinstance(value, list):
        items = [normalize_provider_name(str(item)) for item in value]
    else:
        return ()
    seen: set[str] = set()
    ordered: list[str] = []
    for name in items:
        if name in SUPPORTED_LLM_PROVIDERS and name not in seen:
            ordered.append(name)
            seen.add(name)
    return tuple(ordered)


@dataclass(slots=True)
class Settings:
    vault_path: Path | None = None
    database_path: Path = DEFAULT_DATABASE_PATH
    embedding_model_name: str = DEFAULT_EMBEDDING_MODEL_NAME
    top_k: int = DEFAULT_TOP_K
    enable_llm_synthesis: bool = DEFAULT_ENABLE_LLM_SYNTHESIS
    enable_query_rewrite: bool = DEFAULT_ENABLE_QUERY_REWRITE
    enable_reranking: bool = DEFAULT_ENABLE_RERANKING
    enable_concept_boost: bool = DEFAULT_ENABLE_CONCEPT_BOOST
    llm_provider: str = ""
    fallback_llm_provider: str = ""
    synthesis_model_name: str | None = None
    openai_synthesis_model_name: str = DEFAULT_OPENAI_SYNTHESIS_MODEL_NAME
    gemini_synthesis_model_name: str = DEFAULT_GEMINI_SYNTHESIS_MODEL_NAME
    nvidia_synthesis_model_name: str = DEFAULT_NVIDIA_SYNTHESIS_MODEL_NAME
    ollama_synthesis_model_name: str = DEFAULT_OLLAMA_SYNTHESIS_MODEL_NAME
    mlx_lm_synthesis_model_name: str = DEFAULT_MLX_LM_SYNTHESIS_MODEL_NAME
    openai_api_key: str | None = None
    openai_base_url: str = DEFAULT_OPENAI_BASE_URL
    gemini_api_key: str | None = None
    gemini_base_url: str = DEFAULT_GEMINI_BASE_URL
    nvidia_api_key: str | None = None
    nvidia_base_url: str = DEFAULT_NVIDIA_BASE_URL
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL
    mlx_lm_base_url: str = DEFAULT_MLX_LM_BASE_URL
    ingest_include: tuple[str, ...] = ()
    ingest_exclude: tuple[str, ...] = ()
    use_breadcrumb_embeddings: bool = DEFAULT_USE_BREADCRUMB_EMBEDDINGS
    retrieval_candidate_multiplier: int = DEFAULT_RETRIEVAL_CANDIDATE_MULTIPLIER
    retrieval_candidate_min: int = DEFAULT_RETRIEVAL_CANDIDATE_MIN
    retrieval_candidate_max: int = DEFAULT_RETRIEVAL_CANDIDATE_MAX
    llm_provider_order: tuple[str, ...] = ()
    concept_boost_weight: float = DEFAULT_CONCEPT_BOOST_WEIGHT
    concept_boost_exact_max: float = DEFAULT_CONCEPT_BOOST_EXACT_MAX
    rerank_max_boost: float = DEFAULT_RERANK_MAX_BOOST
    evidence_sufficiency_threshold: float = DEFAULT_EVIDENCE_SUFFICIENCY_THRESHOLD

    def ordered_llm_providers(self) -> tuple[str, ...]:
        """Supported providers in UI order: config order first, then any omitted providers (canonical order)."""
        custom = list(self.llm_provider_order)
        if not custom:
            return SUPPORTED_LLM_PROVIDERS
        seen: set[str] = set()
        out: list[str] = []
        for name in custom:
            if name in SUPPORTED_LLM_PROVIDERS and name not in seen:
                out.append(name)
                seen.add(name)
        for name in SUPPORTED_LLM_PROVIDERS:
            if name not in seen:
                out.append(name)
                seen.add(name)
        return tuple(out)

    def is_supported_provider(self, provider: str | None = None) -> bool:
        provider_name = normalize_provider_name(provider or self.llm_provider)
        return provider_name in SUPPORTED_LLM_PROVIDERS

    def get_synthesis_model_name(self, provider: str | None = None) -> str | None:
        if self.synthesis_model_name:
            return self.synthesis_model_name
        provider_name = normalize_provider_name(provider or self.llm_provider)
        if provider_name == "openai":
            return self.openai_synthesis_model_name
        if provider_name == "gemini":
            return self.gemini_synthesis_model_name
        if provider_name == "nvidia":
            return self.nvidia_synthesis_model_name
        if provider_name == "ollama":
            return self.ollama_synthesis_model_name
        if provider_name == "mlx_lm":
            return self.mlx_lm_synthesis_model_name
        return None

    def synthesis_model_defaults(self) -> dict[str, str]:
        return {
            "openai": self.openai_synthesis_model_name,
            "gemini": self.gemini_synthesis_model_name,
            "nvidia": self.nvidia_synthesis_model_name,
            "ollama": self.ollama_synthesis_model_name,
            "mlx_lm": self.mlx_lm_synthesis_model_name,
        }

    def provider_config(self, provider: str | None = None) -> dict[str, str | None]:
        provider_name = normalize_provider_name(provider or self.llm_provider)
        return {
            "provider": provider_name,
            "model_name": self.get_synthesis_model_name(provider_name),
            "base_url": {
                "openai": self.openai_base_url,
                "gemini": self.gemini_base_url,
                "nvidia": self.nvidia_base_url,
                "ollama": self.ollama_base_url,
                "mlx_lm": self.mlx_lm_base_url,
            }.get(provider_name),
            "api_key": {
                "openai": self.openai_api_key,
                "gemini": self.gemini_api_key,
                "nvidia": self.nvidia_api_key,
                "ollama": None,
                "mlx_lm": None,
            }.get(provider_name),
        }

    def provider_diagnostics(self, provider: str | None = None) -> list[dict[str, str]]:
        provider_name = normalize_provider_name(provider or self.llm_provider)
        diagnostics: list[dict[str, str]] = []
        if not self.is_supported_provider(provider_name):
            diagnostics.append(
                {
                    "code": "unsupported_provider",
                    "field": "LLM_PROVIDER",
                    "message": f"Unsupported LLM_PROVIDER: {provider_name}",
                }
            )
            return diagnostics

        provider_config = self.provider_config(provider_name)
        model_name = str(provider_config.get("model_name") or "").strip()
        model_optional = provider_name in {"mlx_lm"}
        if not model_name and not model_optional:
            diagnostics.append(
                {
                    "code": "missing_provider_model",
                    "field": "SYNTHESIS_MODEL_NAME",
                    "message": f"No synthesis model is configured for provider {provider_name}.",
                }
            )

        base_url = str(provider_config.get("base_url") or "").strip()
        parsed_base_url = urlparse(base_url)
        if not base_url:
            diagnostics.append(
                {
                    "code": "missing_provider_base_url",
                    "field": f"{provider_name.upper()}_BASE_URL",
                    "message": f"No base URL is configured for provider {provider_name}.",
                }
            )
        elif parsed_base_url.scheme not in {"http", "https"} or not parsed_base_url.netloc:
            diagnostics.append(
                {
                    "code": "invalid_provider_base_url",
                    "field": f"{provider_name.upper()}_BASE_URL",
                    "message": f"Base URL for provider {provider_name} must be a valid http(s) URL.",
                }
            )

        requires_api_key = provider_name in {"openai", "gemini", "nvidia"}
        api_key = str(provider_config.get("api_key") or "").strip()
        if requires_api_key and not api_key:
            diagnostics.append(
                {
                    "code": "missing_provider_api_key",
                    "field": f"{provider_name.upper()}_API_KEY",
                    "message": f"{provider_name.upper()}_API_KEY is not configured.",
                }
            )
        return diagnostics

    def provider_availability(self) -> dict[str, dict[str, str | bool]]:
        availability: dict[str, dict[str, str | bool]] = {}
        for provider_name in SUPPORTED_LLM_PROVIDERS:
            diagnostics = self.provider_diagnostics(provider_name)
            availability[provider_name] = {
                "available": not diagnostics,
                "reason": diagnostics[0]["message"] if diagnostics else "",
            }
        if not self.is_supported_provider():
            diagnostics = self.provider_diagnostics(self.llm_provider)
            availability[self.llm_provider] = {
                "available": False,
                "reason": diagnostics[0]["message"] if diagnostics else f"Unsupported LLM_PROVIDER: {self.llm_provider}",
            }
        return availability

    def validate(self) -> list[dict[str, str]]:
        diagnostics: list[dict[str, str]] = []
        if self.top_k < 1:
            diagnostics.append(
                {
                    "code": "invalid_top_k",
                    "field": "TOP_K",
                    "message": "TOP_K must be greater than zero.",
                }
            )
        diagnostics.extend(self.provider_diagnostics())
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


def _parse_positive_float(value: str | float | None, default: float, field_name: str) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number, got {value!r}") from exc
    if parsed < 0:
        return default
    return parsed


def _parse_positive_int(value: str | int | None, default: int, field_name: str) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer.") from exc
    if parsed < 1:
        raise ValueError(f"{field_name} must be greater than zero.")
    return parsed


def _parse_pattern_list(value: str | list | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",")]
    elif isinstance(value, list):
        items = [str(item).strip() for item in value]
    else:
        items = [str(value).strip()]
    return tuple(item for item in items if item)


def format_diagnostics(diagnostics: list[dict[str, str]]) -> list[str]:
    return [item["message"] for item in diagnostics]


def load_settings(config_path: str | None = None) -> Settings:
    file_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    file_values = _load_config_file(file_path if file_path.exists() else None)
    config_dir = file_path.resolve().parent if file_path.exists() else None

    model_value = os.getenv("EMBEDDING_MODEL_NAME", file_values.get("EMBEDDING_MODEL_NAME"))
    top_k_value = os.getenv("TOP_K", file_values.get("TOP_K"))
    enable_value = os.getenv("ENABLE_LLM_SYNTHESIS", file_values.get("ENABLE_LLM_SYNTHESIS"))
    rewrite_value = os.getenv("ENABLE_QUERY_REWRITE", file_values.get("ENABLE_QUERY_REWRITE"))
    reranking_value = os.getenv("ENABLE_RERANKING", file_values.get("ENABLE_RERANKING"))
    concept_boost_value = os.getenv("ENABLE_CONCEPT_BOOST", file_values.get("ENABLE_CONCEPT_BOOST"))
    provider_value = os.getenv("LLM_PROVIDER")
    if provider_value is None:
        provider_value = os.getenv("DEFAULT_LLM_PROVIDER")
    if provider_value is None:
        provider_value = file_values.get("DEFAULT_LLM_PROVIDER")

    fallback_provider_value = os.getenv("FALLBACK_LLM_PROVIDER")
    if fallback_provider_value is None:
        fallback_provider_value = file_values.get("FALLBACK_LLM_PROVIDER")

    primary_llm = normalize_provider_name(str(provider_value)) if provider_value not in (None, "") else ""
    fallback_llm = normalize_provider_name(str(fallback_provider_value)) if fallback_provider_value not in (None, "") else ""
    effective_llm = primary_llm or fallback_llm
    nested_prov = provider_blocks_from_config(file_values)

    synthesis_env = _env_nonempty("SYNTHESIS_MODEL_NAME")
    if synthesis_env is not None:
        synthesis_value: str | None = synthesis_env
    else:
        fv_syn = file_values.get("SYNTHESIS_MODEL_NAME")
        if fv_syn is None or (isinstance(fv_syn, str) and fv_syn.strip() == ""):
            synthesis_value = None
        else:
            synthesis_value = str(fv_syn).strip()

    openai_synthesis_value = _pick_provider_setting(
        "OPENAI_SYNTHESIS_MODEL_NAME",
        nested_prov,
        "openai",
        "synthesis_model_name",
        "OPENAI_SYNTHESIS_MODEL_NAME",
        file_values,
    )
    gemini_synthesis_value = _pick_provider_setting(
        "GEMINI_SYNTHESIS_MODEL_NAME",
        nested_prov,
        "gemini",
        "synthesis_model_name",
        "GEMINI_SYNTHESIS_MODEL_NAME",
        file_values,
    )
    nvidia_synthesis_value = _pick_provider_setting(
        "NVIDIA_SYNTHESIS_MODEL_NAME",
        nested_prov,
        "nvidia",
        "synthesis_model_name",
        "NVIDIA_SYNTHESIS_MODEL_NAME",
        file_values,
    )
    ollama_synthesis_value = _pick_provider_setting(
        "OLLAMA_SYNTHESIS_MODEL_NAME",
        nested_prov,
        "ollama",
        "synthesis_model_name",
        "OLLAMA_SYNTHESIS_MODEL_NAME",
        file_values,
    )
    mlx_lm_synthesis_value = _pick_provider_setting(
        "MLX_LM_SYNTHESIS_MODEL_NAME",
        nested_prov,
        "mlx_lm",
        "synthesis_model_name",
        "MLX_LM_SYNTHESIS_MODEL_NAME",
        file_values,
    )

    openai_api_key = _pick_provider_setting(
        "OPENAI_API_KEY", nested_prov, "openai", "api_key", "OPENAI_API_KEY", file_values
    )
    openai_base_url = _pick_provider_setting(
        "OPENAI_BASE_URL", nested_prov, "openai", "base_url", "OPENAI_BASE_URL", file_values
    )
    gemini_api_key = _pick_provider_setting(
        "GEMINI_API_KEY", nested_prov, "gemini", "api_key", "GEMINI_API_KEY", file_values
    )
    gemini_base_url = _pick_provider_setting(
        "GEMINI_BASE_URL", nested_prov, "gemini", "base_url", "GEMINI_BASE_URL", file_values
    )
    nvidia_api_key = _pick_provider_setting(
        "NVIDIA_API_KEY", nested_prov, "nvidia", "api_key", "NVIDIA_API_KEY", file_values
    )
    nvidia_base_url = _pick_provider_setting(
        "NVIDIA_BASE_URL", nested_prov, "nvidia", "base_url", "NVIDIA_BASE_URL", file_values
    )
    ollama_base_url = _pick_provider_setting(
        "OLLAMA_BASE_URL", nested_prov, "ollama", "base_url", "OLLAMA_BASE_URL", file_values
    )
    mlx_lm_base_url = _pick_provider_setting(
        "MLX_LM_BASE_URL", nested_prov, "mlx_lm", "base_url", "MLX_LM_BASE_URL", file_values
    )
    ingest_include_value = os.getenv("INGEST_INCLUDE", file_values.get("INGEST_INCLUDE"))
    ingest_exclude_value = os.getenv("INGEST_EXCLUDE", file_values.get("INGEST_EXCLUDE"))
    breadcrumb_emb_value = os.getenv("USE_BREADCRUMB_EMBEDDINGS", file_values.get("USE_BREADCRUMB_EMBEDDINGS"))
    retrieval_candidate_multiplier_value = os.getenv(
        "RETRIEVAL_CANDIDATE_MULTIPLIER",
        file_values.get("RETRIEVAL_CANDIDATE_MULTIPLIER"),
    )
    retrieval_candidate_min_value = os.getenv(
        "RETRIEVAL_CANDIDATE_MIN",
        file_values.get("RETRIEVAL_CANDIDATE_MIN"),
    )
    retrieval_candidate_max_value = os.getenv(
        "RETRIEVAL_CANDIDATE_MAX",
        file_values.get("RETRIEVAL_CANDIDATE_MAX"),
    )
    concept_boost_weight_value = os.getenv("CONCEPT_BOOST_WEIGHT", file_values.get("CONCEPT_BOOST_WEIGHT"))
    concept_boost_exact_max_value = os.getenv("CONCEPT_BOOST_EXACT_MAX", file_values.get("CONCEPT_BOOST_EXACT_MAX"))
    rerank_max_boost_value = os.getenv("RERANK_MAX_BOOST", file_values.get("RERANK_MAX_BOOST"))
    evidence_threshold_value = os.getenv("EVIDENCE_SUFFICIENCY_THRESHOLD", file_values.get("EVIDENCE_SUFFICIENCY_THRESHOLD"))
    order_env = os.getenv("LLM_PROVIDER_ORDER")
    order_file = file_values.get("LLM_PROVIDER_ORDER")
    order_value = order_env if order_env is not None else order_file

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
        top_k=_parse_positive_int(top_k_value, DEFAULT_TOP_K, "TOP_K"),
        enable_llm_synthesis=_parse_bool(enable_value, DEFAULT_ENABLE_LLM_SYNTHESIS),
        enable_query_rewrite=_parse_bool(rewrite_value, DEFAULT_ENABLE_QUERY_REWRITE),
        enable_reranking=_parse_bool(reranking_value, DEFAULT_ENABLE_RERANKING),
        enable_concept_boost=_parse_bool(concept_boost_value, DEFAULT_ENABLE_CONCEPT_BOOST),
        llm_provider=effective_llm,
        fallback_llm_provider=fallback_llm,
        synthesis_model_name=synthesis_value,
        openai_synthesis_model_name=openai_synthesis_value or DEFAULT_OPENAI_SYNTHESIS_MODEL_NAME,
        gemini_synthesis_model_name=gemini_synthesis_value or DEFAULT_GEMINI_SYNTHESIS_MODEL_NAME,
        nvidia_synthesis_model_name=nvidia_synthesis_value or DEFAULT_NVIDIA_SYNTHESIS_MODEL_NAME,
        ollama_synthesis_model_name=ollama_synthesis_value or synthesis_value or DEFAULT_OLLAMA_SYNTHESIS_MODEL_NAME,
        mlx_lm_synthesis_model_name=mlx_lm_synthesis_value or DEFAULT_MLX_LM_SYNTHESIS_MODEL_NAME,
        openai_api_key=openai_api_key,
        openai_base_url=openai_base_url or DEFAULT_OPENAI_BASE_URL,
        gemini_api_key=gemini_api_key,
        gemini_base_url=gemini_base_url or DEFAULT_GEMINI_BASE_URL,
        nvidia_api_key=nvidia_api_key,
        nvidia_base_url=nvidia_base_url or DEFAULT_NVIDIA_BASE_URL,
        ollama_base_url=ollama_base_url or DEFAULT_OLLAMA_BASE_URL,
        mlx_lm_base_url=mlx_lm_base_url or DEFAULT_MLX_LM_BASE_URL,
        ingest_include=_parse_pattern_list(ingest_include_value),
        ingest_exclude=_parse_pattern_list(ingest_exclude_value),
        use_breadcrumb_embeddings=_parse_bool(breadcrumb_emb_value, DEFAULT_USE_BREADCRUMB_EMBEDDINGS),
        retrieval_candidate_multiplier=_parse_positive_int(
            retrieval_candidate_multiplier_value,
            DEFAULT_RETRIEVAL_CANDIDATE_MULTIPLIER,
            "RETRIEVAL_CANDIDATE_MULTIPLIER",
        ),
        retrieval_candidate_min=_parse_positive_int(
            retrieval_candidate_min_value,
            DEFAULT_RETRIEVAL_CANDIDATE_MIN,
            "RETRIEVAL_CANDIDATE_MIN",
        ),
        retrieval_candidate_max=_parse_positive_int(
            retrieval_candidate_max_value,
            DEFAULT_RETRIEVAL_CANDIDATE_MAX,
            "RETRIEVAL_CANDIDATE_MAX",
        ),
        llm_provider_order=_parse_provider_order(order_value),
        concept_boost_weight=_parse_positive_float(concept_boost_weight_value, DEFAULT_CONCEPT_BOOST_WEIGHT, "CONCEPT_BOOST_WEIGHT"),
        concept_boost_exact_max=_parse_positive_float(concept_boost_exact_max_value, DEFAULT_CONCEPT_BOOST_EXACT_MAX, "CONCEPT_BOOST_EXACT_MAX"),
        rerank_max_boost=_parse_positive_float(rerank_max_boost_value, DEFAULT_RERANK_MAX_BOOST, "RERANK_MAX_BOOST"),
        evidence_sufficiency_threshold=_parse_positive_float(evidence_threshold_value, DEFAULT_EVIDENCE_SUFFICIENCY_THRESHOLD, "EVIDENCE_SUFFICIENCY_THRESHOLD"),
    )
