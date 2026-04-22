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
