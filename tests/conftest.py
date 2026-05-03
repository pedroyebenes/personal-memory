from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.db import connect, init_db


@pytest.fixture()
def fixture_vault() -> Path:
    return Path(__file__).parent / "fixtures" / "vault"


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        vault_path=None,
        database_path=tmp_path / "memory.sqlite3",
        embedding_model_name="test-model",
        top_k=5,
        enable_llm_synthesis=False,
        synthesis_model_name=None,
        llm_provider="ollama",
        fallback_llm_provider="ollama",
    )


@pytest.fixture()
def connection(settings: Settings):
    conn = connect(settings.database_path)
    init_db(conn)
    yield conn
    conn.close()
