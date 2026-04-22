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


def test_ingest_prunes_removed_note(connection, tmp_path: Path, fixture_vault: Path, settings: Settings) -> None:
    vault_copy = tmp_path / "vault"
    vault_copy.mkdir()
    for source in fixture_vault.iterdir():
        (vault_copy / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    ingest_vault(connection, vault_copy, settings)
    (vault_copy / "wiki-links.md").unlink()
    summary = ingest_vault(connection, vault_copy, settings)
    assert summary["pruned"] == 1
    document_count = connection.execute("SELECT COUNT(*) AS count FROM documents").fetchone()["count"]
    assert document_count == 2


def test_ingest_switches_to_new_vault_without_leaking_old_documents(connection, tmp_path: Path, fixture_vault: Path, settings: Settings) -> None:
    first_vault = tmp_path / "first"
    second_vault = tmp_path / "second"
    first_vault.mkdir()
    second_vault.mkdir()

    for source in fixture_vault.iterdir():
        (first_vault / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    (second_vault / "other-note.md").write_text(
        "# Different Corpus\n\nThis vault is about gardening and tomato seedlings.\n",
        encoding="utf-8",
    )

    ingest_vault(connection, first_vault, settings)
    summary = ingest_vault(connection, second_vault, settings)
    assert summary["pruned"] == 3
    rows = connection.execute("SELECT source_path FROM documents").fetchall()
    assert len(rows) == 1
    assert rows[0]["source_path"].endswith("other-note.md")


def test_search_and_ask_commands(connection, fixture_vault: Path, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)
    search_results = hybrid_search(connection, "North Star", settings, top_k=2)
    assert search_results
    response = answer_question(connection, "What is North Star?", settings, top_k=2)
    assert response["sources"]
    assert response["question"] == "What is North Star?"
