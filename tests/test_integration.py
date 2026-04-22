from __future__ import annotations

import json
from pathlib import Path

from app.cli import main
from app.config import Settings
from app.ingest.register import ingest_vault, reindex_vault
from app.retrieval.hybrid_search import hybrid_search
from app.retrieval.qa import answer_question


def test_ingest_sample_vault(connection, fixture_vault: Path, settings: Settings) -> None:
    summary = ingest_vault(connection, fixture_vault, settings)
    assert summary["indexed"] == 3
    document_count = connection.execute("SELECT COUNT(*) AS count FROM documents").fetchone()["count"]
    assert document_count == 3


def test_update_one_note_and_reindex(connection, tmp_path: Path, fixture_vault: Path, settings: Settings) -> None:
    vault_copy = tmp_path / "vault"
    vault_copy.mkdir()
    for source in fixture_vault.iterdir():
        (vault_copy / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    ingest_vault(connection, vault_copy, settings)
    note = vault_copy / "plain-note.md"
    note.write_text(note.read_text(encoding="utf-8") + "\n\nFresh update about retrieval.\n", encoding="utf-8")
    summary = reindex_vault(connection, vault_copy, settings)
    assert summary["indexed"] == 3
    results = hybrid_search(connection, "Fresh update", settings, top_k=2)
    assert results


def test_search_and_ask_commands(connection, fixture_vault: Path, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)
    search_results = hybrid_search(connection, "North Star", settings, top_k=2)
    assert search_results
    response = answer_question(connection, "What is North Star?", settings, top_k=2)
    assert response["sources"]
    assert response["question"] == "What is North Star?"
