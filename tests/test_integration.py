from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from app.cli import main
from app.config import Settings
from app.ingest import register
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


def test_status_command_includes_config_diagnostics(tmp_path: Path, monkeypatch, capsys) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "VAULT_PATH": str(tmp_path / "missing-vault"),
                "DATABASE_PATH": str(tmp_path / "memory.sqlite3"),
                "LLM_PROVIDER": "invalid-provider",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "argv", ["personal-memory", "--config", str(config_path), "status"])

    main()

    payload = json.loads(capsys.readouterr().out)
    assert {item["code"] for item in payload["config_diagnostics"]} == {"unsupported_provider", "vault_not_found"}


def test_concepts_show_command_resolves_alias(
    connection,
    fixture_vault: Path,
    settings: Settings,
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    ingest_vault(connection, fixture_vault, settings)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "DATABASE_PATH": str(settings.database_path),
                "EMBEDDING_MODEL_NAME": settings.embedding_model_name,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["personal-memory", "--config", str(config_path), "concepts", "show", "--name", "North Star"],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["normalized_key"] == "project north star"
    assert any(mention["extraction_method"] == "alias" for mention in payload["mentions"])


def test_concepts_list_and_refresh_commands(
    connection,
    fixture_vault: Path,
    settings: Settings,
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    ingest_vault(connection, fixture_vault, settings)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "DATABASE_PATH": str(settings.database_path),
                "EMBEDDING_MODEL_NAME": settings.embedding_model_name,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        ["personal-memory", "--config", str(config_path), "concepts", "list", "--search", "north"],
    )
    main()
    listed = json.loads(capsys.readouterr().out)
    assert any(item["normalized_key"] == "project north star" for item in listed["concepts"])

    connection.execute("DELETE FROM entity_mentions")
    connection.execute("DELETE FROM entities")
    connection.commit()

    monkeypatch.setattr(
        sys,
        "argv",
        ["personal-memory", "--config", str(config_path), "concepts", "refresh"],
    )
    main()
    refreshed = json.loads(capsys.readouterr().out)
    assert refreshed["entities"] > 0
    assert refreshed["mentions"] > 0


def test_ingest_isolates_per_file_failures(connection, fixture_vault: Path, settings: Settings, monkeypatch) -> None:
    original = register._ingest_single_document
    calls = {"count": 0}

    def flaky_ingest(conn, entry, settings):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("boom")
        return original(conn, entry, settings)

    monkeypatch.setattr(register, "_ingest_single_document", flaky_ingest)

    summary = ingest_vault(connection, fixture_vault, settings)

    assert summary["status"] == "completed_with_errors"
    assert summary["failed"] == 1
    assert summary["indexed"] == 2
    assert summary["failures"][0]["error"] == "boom"
    latest_run = connection.execute("SELECT status FROM ingestion_runs ORDER BY id DESC LIMIT 1").fetchone()
    assert latest_run["status"] == "completed_with_errors"


def test_reindex_isolates_per_file_failures(connection, fixture_vault: Path, settings: Settings, monkeypatch) -> None:
    original = register.parse_markdown_file
    calls = {"count": 0}

    def flaky_parse(path):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("boom")
        return original(path)

    monkeypatch.setattr(register, "parse_markdown_file", flaky_parse)

    summary = reindex_vault(connection, fixture_vault, settings)

    assert summary["status"] == "completed_with_errors"
    assert summary["failed"] == 1
    assert summary["indexed"] == 2
    assert any(failure["error"] == "boom" for failure in summary["failures"])
    latest_run = connection.execute("SELECT status FROM ingestion_runs ORDER BY id DESC LIMIT 1").fetchone()
    assert latest_run["status"] == "completed_with_errors"


def test_ingest_marks_run_failed_when_scanner_raises(connection, fixture_vault: Path, settings: Settings, monkeypatch) -> None:
    monkeypatch.setattr(
        register,
        "scan_markdown_entries",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk gone")),
    )

    with pytest.raises(OSError, match="disk gone"):
        ingest_vault(connection, fixture_vault, settings)

    latest_run = connection.execute("SELECT status FROM ingestion_runs ORDER BY id DESC LIMIT 1").fetchone()
    assert latest_run["status"] == "failed"
