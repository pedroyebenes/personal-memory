from __future__ import annotations

from pathlib import Path

from app.config import load_settings


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
    settings = load_settings(None)
    availability = settings.provider_availability()

    assert availability["ollama"]["available"] is True
    assert availability["openai"]["available"] is False
    assert availability["gemini"]["available"] is False
    assert availability["nvidia"]["available"] is False
