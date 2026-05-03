from __future__ import annotations

from pathlib import Path

from app.config import (
    SUPPORTED_LLM_PROVIDERS,
    Settings,
    format_diagnostics,
    load_settings,
    provider_blocks_from_config,
)


def test_load_settings_reads_json_config_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """
        {
          "VAULT_PATH": "./vault",
          "DATABASE_PATH": "./data/cache/test.sqlite3",
          "TOP_K": 9,
          "ENABLE_QUERY_REWRITE": true,
          "ENABLE_CONCEPT_BOOST": true,
          "FALLBACK_LLM_PROVIDER": "ollama"
        }
        """.strip(),
        encoding="utf-8",
    )

    settings = load_settings(str(config_path))

    assert settings.vault_path == (tmp_path / "vault").resolve()
    assert settings.database_path == tmp_path / "data/cache/test.sqlite3"
    assert settings.top_k == 9
    assert settings.enable_query_rewrite is True
    assert settings.enable_concept_boost is True
    assert settings.fallback_llm_provider == "ollama"
    assert settings.llm_provider == "ollama"


def test_environment_variables_override_json_config(
    tmp_path: Path, monkeypatch
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """
        {
          "TOP_K": 3,
          "DEFAULT_LLM_PROVIDER": "gemini"
        }
        """.strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("TOP_K", "11")
    monkeypatch.setenv("LLM_PROVIDER", "openai")

    settings = load_settings(str(config_path))

    assert settings.top_k == 11
    assert settings.llm_provider == "openai"


def test_load_settings_reads_default_llm_provider_alias(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text('{"DEFAULT_LLM_PROVIDER": "gemini"}', encoding="utf-8")

    settings = load_settings(str(config_path))

    assert settings.llm_provider == "gemini"
    assert settings.fallback_llm_provider == ""


def test_load_settings_fallback_used_when_no_primary_default(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text('{"FALLBACK_LLM_PROVIDER": "gemini"}', encoding="utf-8")

    settings = load_settings(str(config_path))

    assert settings.llm_provider == "gemini"
    assert settings.fallback_llm_provider == "gemini"


def test_provider_blocks_from_config_collects_nested_and_top_level() -> None:
    raw = {
        "PROVIDERS": {
            "openai": {"api_key": "sk-nested", "base_url": "https://api.example/v1"},
        },
        "NVIDIA": {
            "api_key": "nv-nested",
            "base_url": "https://nv.example/v1",
            "model": "custom-model",
        },
    }
    blocks = provider_blocks_from_config(raw)
    assert blocks["openai"]["api_key"] == "sk-nested"
    assert blocks["openai"]["base_url"] == "https://api.example/v1"
    assert blocks["nvidia"]["api_key"] == "nv-nested"
    assert blocks["nvidia"]["synthesis_model_name"] == "custom-model"


def test_load_settings_nested_providers_merge_with_flat(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """
        {
          "FALLBACK_LLM_PROVIDER": "ollama",
          "OPENAI_API_KEY": "flat-key",
          "PROVIDERS": {
            "openai": { "api_key": "nested-wins", "base_url": "https://nested.example/v1" }
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    settings = load_settings(str(config_path))

    assert settings.openai_api_key == "nested-wins"
    assert settings.openai_base_url == "https://nested.example/v1"


def test_load_settings_primary_default_over_fallback(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"DEFAULT_LLM_PROVIDER": "gemini", "FALLBACK_LLM_PROVIDER": "ollama"}',
        encoding="utf-8",
    )

    settings = load_settings(str(config_path))

    assert settings.llm_provider == "gemini"
    assert settings.fallback_llm_provider == "ollama"


def test_load_settings_json_does_not_read_legacy_llm_provider_key(tmp_path: Path) -> None:
    """config.json must use DEFAULT_LLM_PROVIDER / FALLBACK_LLM_PROVIDER; legacy LLM_PROVIDER is ignored."""
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"LLM_PROVIDER": "gemini", "FALLBACK_LLM_PROVIDER": "openai"}',
        encoding="utf-8",
    )

    settings = load_settings(str(config_path))

    assert settings.llm_provider == "openai"
    assert settings.fallback_llm_provider == "openai"


def test_load_settings_reads_reranking_flag(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text('{"ENABLE_RERANKING": false}', encoding="utf-8")
    monkeypatch.setenv("ENABLE_RERANKING", "true")

    settings = load_settings(str(config_path))

    assert settings.enable_reranking is True


def test_load_settings_reads_nvidia_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """
        {
          "DEFAULT_LLM_PROVIDER": "nvidia",
          "NVIDIA_SYNTHESIS_MODEL_NAME": "z-ai/glm-4.7",
          "NVIDIA_API_KEY": "nvapi-test",
          "NVIDIA_BASE_URL": "https://integrate.api.nvidia.com/v1"
        }
        """.strip(),
        encoding="utf-8",
    )

    settings = load_settings(str(config_path))

    assert settings.llm_provider == "nvidia"
    assert settings.nvidia_api_key == "nvapi-test"
    assert settings.nvidia_base_url == "https://integrate.api.nvidia.com/v1"
    assert settings.get_synthesis_model_name() == "z-ai/glm-4.7"


def test_load_settings_reads_mlx_lm_config_and_normalizes_provider(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """
        {
          "DEFAULT_LLM_PROVIDER": "mlx-lm",
          "MLX_LM_SYNTHESIS_MODEL_NAME": "mlx-community/Mistral-7B-Instruct-v0.3-4bit",
          "MLX_LM_BASE_URL": "http://localhost:8080/v1"
        }
        """.strip(),
        encoding="utf-8",
    )

    settings = load_settings(str(config_path))

    assert settings.llm_provider == "mlx_lm"
    assert settings.mlx_lm_base_url == "http://localhost:8080/v1"
    assert settings.get_synthesis_model_name() == "mlx-community/Mistral-7B-Instruct-v0.3-4bit"


def test_load_settings_uses_provider_specific_model_defaults(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """
        {
          "DEFAULT_LLM_PROVIDER": "ollama",
          "OPENAI_SYNTHESIS_MODEL_NAME": "gpt-5-mini",
          "GEMINI_SYNTHESIS_MODEL_NAME": "gemini-2.5-flash",
          "NVIDIA_SYNTHESIS_MODEL_NAME": "z-ai/glm-4.7",
          "OLLAMA_SYNTHESIS_MODEL_NAME": "gemma4:e2b",
          "MLX_LM_SYNTHESIS_MODEL_NAME": "mlx-community/Qwen3-4B-4bit"
        }
        """.strip(),
        encoding="utf-8",
    )

    settings = load_settings(str(config_path))

    assert settings.get_synthesis_model_name("openai") == "gpt-5-mini"
    assert settings.get_synthesis_model_name("gemini") == "gemini-2.5-flash"
    assert settings.get_synthesis_model_name("nvidia") == "z-ai/glm-4.7"
    assert settings.get_synthesis_model_name("ollama") == "gemma4:e2b"
    assert settings.get_synthesis_model_name("mlx-lm") == "mlx-community/Qwen3-4B-4bit"


def test_ordered_llm_providers_uses_supported_order_when_unconfigured() -> None:
    settings = Settings()
    assert settings.ordered_llm_providers() == SUPPORTED_LLM_PROVIDERS


def test_ordered_llm_providers_partial_list_appends_remaining_in_canonical_order() -> None:
    settings = Settings(llm_provider_order=("nvidia", "gemini"))
    ordered = settings.ordered_llm_providers()
    assert ordered[:2] == ("nvidia", "gemini")
    assert set(ordered) == set(SUPPORTED_LLM_PROVIDERS)


def test_load_settings_reads_llm_provider_order_json_array(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text('{"LLM_PROVIDER_ORDER": ["openai", "ollama"]}', encoding="utf-8")

    settings = load_settings(str(config_path))

    assert settings.llm_provider_order == ("openai", "ollama")


def test_load_settings_reads_llm_provider_order_comma_string(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text('{"LLM_PROVIDER_ORDER": "gemini, mlx_lm , invalid"}', encoding="utf-8")

    settings = load_settings(str(config_path))

    assert settings.llm_provider_order == ("gemini", "mlx_lm")


def test_provider_availability_marks_missing_keys() -> None:
    settings = Settings(
        llm_provider="ollama",
        openai_api_key=None,
        gemini_api_key=None,
        nvidia_api_key=None,
    )
    availability = settings.provider_availability()

    assert availability["ollama"]["available"] is True
    assert availability["openai"]["available"] is False
    assert availability["gemini"]["available"] is False
    assert availability["nvidia"]["available"] is False
    assert availability["mlx_lm"]["available"] is True


def test_validate_reports_invalid_provider_and_missing_vault(tmp_path: Path) -> None:
    settings = load_settings(None)
    settings.llm_provider = "invalid-provider"
    settings.vault_path = tmp_path / "missing-vault"

    diagnostics = settings.validate()

    assert {item["code"] for item in diagnostics} == {
        "unsupported_provider",
        "vault_not_found",
    }


def test_validate_reports_provider_model_and_base_url_problems() -> None:
    settings = load_settings(None)
    settings.llm_provider = "ollama"
    settings.ollama_synthesis_model_name = ""
    settings.ollama_base_url = "not-a-url"

    diagnostics = settings.validate()

    assert {item["code"] for item in diagnostics} >= {
        "missing_provider_model",
        "invalid_provider_base_url",
    }


def test_load_settings_rejects_invalid_top_k(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text('{"TOP_K": 0}', encoding="utf-8")

    try:
        load_settings(str(config_path))
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected ValueError")

    assert message == "TOP_K must be greater than zero."


def test_format_diagnostics_returns_messages_only() -> None:
    messages = format_diagnostics(
        [
            {"code": "one", "field": "A", "message": "First issue"},
            {"code": "two", "field": "B", "message": "Second issue"},
        ]
    )

    assert messages == ["First issue", "Second issue"]
