from __future__ import annotations

from pathlib import Path

from app.config import Settings, format_diagnostics, load_settings


def test_load_settings_reads_json_config_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """
        {
          "VAULT_PATH": "./vault",
          "DATABASE_PATH": "./data/cache/test.sqlite3",
          "TOP_K": 9,
          "ENABLE_QUERY_REWRITE": true
        }
        """.strip(),
        encoding="utf-8",
    )

    settings = load_settings(str(config_path))

    assert settings.vault_path == (tmp_path / "vault").resolve()
    assert settings.database_path == tmp_path / "data/cache/test.sqlite3"
    assert settings.top_k == 9
    assert settings.enable_query_rewrite is True


def test_environment_variables_override_json_config(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """
        {
          "TOP_K": 3,
          "LLM_PROVIDER": "gemini"
        }
        """.strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("TOP_K", "11")
    monkeypatch.setenv("LLM_PROVIDER", "openai")

    settings = load_settings(str(config_path))

    assert settings.top_k == 11
    assert settings.llm_provider == "openai"


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
          "LLM_PROVIDER": "nvidia",
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


def test_load_settings_uses_provider_specific_model_defaults(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """
        {
          "LLM_PROVIDER": "ollama",
          "OPENAI_SYNTHESIS_MODEL_NAME": "gpt-5-mini",
          "GEMINI_SYNTHESIS_MODEL_NAME": "gemini-2.5-flash",
          "NVIDIA_SYNTHESIS_MODEL_NAME": "z-ai/glm-4.7",
          "OLLAMA_SYNTHESIS_MODEL_NAME": "gemma4:e4b-it-q4_K_M"
        }
        """.strip(),
        encoding="utf-8",
    )

    settings = load_settings(str(config_path))

    assert settings.get_synthesis_model_name("openai") == "gpt-5-mini"
    assert settings.get_synthesis_model_name("gemini") == "gemini-2.5-flash"
    assert settings.get_synthesis_model_name("nvidia") == "z-ai/glm-4.7"
    assert settings.get_synthesis_model_name("ollama") == "gemma4:e4b-it-q4_K_M"


def test_provider_availability_marks_missing_keys() -> None:
    settings = Settings(
        openai_api_key=None,
        gemini_api_key=None,
        nvidia_api_key=None,
    )
    availability = settings.provider_availability()

    assert availability["ollama"]["available"] is True
    assert availability["openai"]["available"] is False
    assert availability["gemini"]["available"] is False
    assert availability["nvidia"]["available"] is False


def test_validate_reports_invalid_provider_and_missing_vault(tmp_path: Path) -> None:
    settings = load_settings(None)
    settings.llm_provider = "invalid-provider"
    settings.vault_path = tmp_path / "missing-vault"

    diagnostics = settings.validate()

    assert {item["code"] for item in diagnostics} == {"unsupported_provider", "vault_not_found"}


def test_validate_reports_provider_model_and_base_url_problems() -> None:
    settings = load_settings(None)
    settings.llm_provider = "ollama"
    settings.ollama_synthesis_model_name = ""
    settings.ollama_base_url = "not-a-url"

    diagnostics = settings.validate()

    assert {item["code"] for item in diagnostics} >= {"missing_provider_model", "invalid_provider_base_url"}


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
