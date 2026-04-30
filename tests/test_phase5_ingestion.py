from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings, load_settings
import json

from app.ingest.register import ingest_vault, rebuild_chunk_vectors, rebuild_embeddings, reindex_vault
from app.retrieval.hybrid_search import hybrid_search
from app.vault.obsidian_parser import parse_markdown_file
from app.vault.scanner import scan_markdown_entries, scan_markdown_files


def _write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_malformed_frontmatter_does_not_break_parsing(tmp_path: Path) -> None:
    note = _write(
        tmp_path / "broken.md",
        "---\n: : invalid yaml\n  - x\n: nope\n---\n\n# Body\n\nContent.",
    )

    parsed, warnings = parse_markdown_file(note)

    assert parsed.title == "broken"
    assert parsed.normalized_text.startswith("# Body")
    assert parsed.frontmatter == {}
    assert any("frontmatter" in warning for warning in warnings)


def test_frontmatter_non_mapping_is_warned_and_dropped(tmp_path: Path) -> None:
    note = _write(tmp_path / "list-fm.md", "---\n- one\n- two\n---\n\nBody")

    parsed, warnings = parse_markdown_file(note)

    assert parsed.frontmatter == {}
    assert any("not a mapping" in warning for warning in warnings)


def test_tags_and_aliases_are_deduplicated_and_coerced(tmp_path: Path) -> None:
    note = _write(
        tmp_path / "tags.md",
        "---\n"
        "title: Notes\n"
        "tags:\n  - alpha\n  - alpha\n  - 2026\n  - ''\n"
        "aliases:\n  - First\n  - first\n"
        "---\n\nBody",
    )

    parsed, warnings = parse_markdown_file(note)

    assert parsed.tags == ["alpha", "2026"]
    assert parsed.aliases == ["First", "first"]
    assert warnings == []


def test_tags_dict_is_coerced_with_warning(tmp_path: Path) -> None:
    note = _write(
        tmp_path / "weird-tags.md",
        "---\ntags:\n  inner: value\n---\n\nBody",
    )

    _, warnings = parse_markdown_file(note)

    assert any("'tags'" in warning for warning in warnings)


def test_ingest_returns_change_set_for_derived_layers(connection, tmp_path: Path, settings: Settings) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(vault / "alpha.md", "# Alpha\n\nFirst note.\n")
    _write(vault / "beta.md", "# Beta\n\nSecond note.\n")

    summary = ingest_vault(connection, vault, settings)

    assert summary["status"] == "completed"
    assert summary["indexed"] == 2
    assert sorted(summary["changed_document_ids"]) == [
        int(row["id"])
        for row in connection.execute("SELECT id FROM documents ORDER BY id").fetchall()
    ]
    assert summary["removed_document_ids"] == []


def test_ingest_change_set_lists_only_modified_documents(connection, tmp_path: Path, settings: Settings) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    note_a = _write(vault / "alpha.md", "# Alpha\n\nFirst note.\n")
    _write(vault / "beta.md", "# Beta\n\nSecond note.\n")
    ingest_vault(connection, vault, settings)

    # Touch only one note and bump its mtime so it counts as changed.
    note_a.write_text("# Alpha\n\nUpdated body.\n", encoding="utf-8")
    bumped = datetime(2030, 1, 1, tzinfo=timezone.utc).timestamp()
    os.utime(note_a, (bumped, bumped))

    summary = ingest_vault(connection, vault, settings)

    changed_paths = {
        row["source_path"]
        for row in connection.execute(
            "SELECT source_path FROM documents WHERE id IN ({})".format(
                ",".join(str(int(doc_id)) for doc_id in summary["changed_document_ids"]) or "NULL"
            )
        ).fetchall()
    }
    assert changed_paths == {str(note_a)}
    assert summary["indexed"] == 1
    assert summary["skipped"] == 1


def test_ingest_skips_unchanged_files_without_reading(connection, tmp_path: Path, settings: Settings, monkeypatch) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(vault / "alpha.md", "# Alpha\n\nNote.\n")

    ingest_vault(connection, vault, settings)

    from app.ingest import register

    def fail_parse(_):
        raise AssertionError("parse_markdown_file should not be called for an unchanged file")

    monkeypatch.setattr(register, "parse_markdown_file", fail_parse)

    summary = ingest_vault(connection, vault, settings)

    assert summary["skipped"] == 1
    assert summary["indexed"] == 0
    assert summary["failed"] == 0


def test_ingest_skips_when_mtime_changes_but_content_does_not(connection, tmp_path: Path, settings: Settings) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    note = _write(vault / "alpha.md", "# Alpha\n\nNote.\n")
    ingest_vault(connection, vault, settings)
    bumped = datetime(2031, 1, 1, tzinfo=timezone.utc).timestamp()
    os.utime(note, (bumped, bumped))

    summary = ingest_vault(connection, vault, settings)

    assert summary["skipped"] == 1
    assert summary["indexed"] == 0


def test_ingest_records_per_file_failures_for_unreadable_files(connection, tmp_path: Path, settings: Settings, monkeypatch) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(vault / "alpha.md", "# Alpha\n\nNote.\n")
    bad = _write(vault / "broken.md", "")

    from app.ingest import register

    original = register.parse_markdown_file

    def selective_parse(path):
        if path == bad:
            raise UnicodeDecodeError("utf-8", b"", 0, 1, "invalid start byte")
        return original(path)

    monkeypatch.setattr(register, "parse_markdown_file", selective_parse)

    summary = ingest_vault(connection, vault, settings)

    assert summary["status"] == "completed_with_errors"
    assert summary["indexed"] == 1
    assert summary["failed"] == 1
    assert summary["failures"][0]["path"].endswith("broken.md")
    assert summary["failures"][0]["error_type"] == "UnicodeDecodeError"


def test_ingest_surfaces_warnings_for_malformed_frontmatter(connection, tmp_path: Path, settings: Settings) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(
        vault / "noisy.md",
        "---\n: bad\n  - oops\n---\n\n# Body\n\nText.",
    )

    summary = ingest_vault(connection, vault, settings)

    assert summary["indexed"] == 1
    assert summary["failed"] == 0
    assert summary["warnings"]
    assert summary["warnings"][0]["path"].endswith("noisy.md")


def test_scanner_applies_include_and_exclude_globs(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "drafts").mkdir(parents=True)
    (vault / "notes").mkdir()
    _write(vault / "notes" / "keep.md", "keep")
    _write(vault / "notes" / "skip.md", "skip")
    _write(vault / "drafts" / "ignore.md", "ignore")

    included = scan_markdown_files(vault, include=["notes/*.md"])
    assert {p.name for p in included} == {"keep.md", "skip.md"}

    excluded = scan_markdown_files(vault, exclude=["drafts/*", "notes/skip.md"])
    assert {p.name for p in excluded} == {"keep.md"}

    entries = scan_markdown_entries(vault, exclude=["drafts/*"])
    assert {entry.path.name for entry in entries} == {"keep.md", "skip.md"}
    assert all(entry.size >= 0 and entry.mtime_iso for entry in entries)


def test_ingest_respects_scope_settings(connection, tmp_path: Path, settings: Settings) -> None:
    vault = tmp_path / "vault"
    (vault / "drafts").mkdir(parents=True)
    (vault / "notes").mkdir()
    _write(vault / "notes" / "kept.md", "# Kept\n\nIndexed.")
    _write(vault / "drafts" / "skipped.md", "# Skipped\n\nIgnored.")

    settings.ingest_exclude = ("drafts/*",)
    summary = ingest_vault(connection, vault, settings)

    assert summary["indexed"] == 1
    rows = connection.execute("SELECT source_path FROM documents").fetchall()
    paths = [row["source_path"] for row in rows]
    assert all("drafts" not in path for path in paths)
    assert summary["scope"]["exclude"] == ["drafts/*"]


def test_load_settings_parses_include_and_exclude(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"INGEST_INCLUDE": ["notes/*.md"], "INGEST_EXCLUDE": "archive/*,drafts/*"}',
        encoding="utf-8",
    )

    settings = load_settings(str(config_path))

    assert settings.ingest_include == ("notes/*.md",)
    assert settings.ingest_exclude == ("archive/*", "drafts/*")


def test_reindex_returns_change_set_and_status(connection, tmp_path: Path, settings: Settings) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(vault / "alpha.md", "# Alpha\n\nFirst.\n")
    _write(vault / "beta.md", "# Beta\n\nSecond.\n")

    summary = reindex_vault(connection, vault, settings)

    assert summary["status"] == "completed"
    assert summary["indexed"] == 2
    assert len(summary["changed_document_ids"]) == 2
    assert summary["scope"] == {"include": [], "exclude": []}


def test_ingest_records_file_size_and_mtime(connection, tmp_path: Path, settings: Settings) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    note = _write(vault / "alpha.md", "# Alpha\n\nNote with body.\n")

    ingest_vault(connection, vault, settings)

    row = connection.execute(
        "SELECT file_size, last_modified FROM documents WHERE source_path = ?",
        (str(note),),
    ).fetchone()
    assert int(row["file_size"]) == note.stat().st_size
    expected = (
        datetime.fromtimestamp(note.stat().st_mtime, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
    )
    assert row["last_modified"] == expected


def test_ingest_persists_heading_path_json(connection, tmp_path: Path, settings: Settings) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(vault / "note.md", "# A\n\nx\n\n## B\n\ny\n")

    ingest_vault(connection, vault, settings)

    rows = connection.execute(
        """
        SELECT chunk_index, heading_path_json FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.source_path LIKE '%note.md%'
        ORDER BY chunk_index
        """
    ).fetchall()
    paths = [json.loads(r["heading_path_json"]) for r in rows]
    assert paths
    assert any("A" in p and "B" in p for p in paths)


def test_single_document_ingest_rebinds_mentions_and_prunes_orphans(
    connection, tmp_path: Path, settings: Settings
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "note.md"
    note.write_text("# Doc\n\nSee [[LonelyWikilink]] for details.\n", encoding="utf-8")
    ingest_vault(connection, vault, settings)

    row = connection.execute(
        "SELECT id, mention_count FROM entities WHERE canonical_name = ?",
        ("LonelyWikilink",),
    ).fetchone()
    assert row is not None
    assert int(row["mention_count"]) >= 1
    entity_id = int(row["id"])

    note.write_text("# Doc\n\nNo wikilinks in this body.\n", encoding="utf-8")

    bumped = datetime(2032, 6, 1, tzinfo=timezone.utc).timestamp()
    os.utime(note, (bumped, bumped))

    ingest_vault(connection, vault, settings)

    assert connection.execute("SELECT id FROM entities WHERE id = ?", (entity_id,)).fetchone() is None


def test_rebuild_embeddings_is_idempotent_without_breadcrumbs(
    connection, fixture_vault: Path, settings: Settings
) -> None:
    settings.use_breadcrumb_embeddings = False
    ingest_vault(connection, fixture_vault, settings)
    query = "weekly review"
    before = hybrid_search(connection, query, settings, top_k=5)
    ids_before = [r.chunk_id for r in before]

    summary = rebuild_embeddings(connection, settings, use_breadcrumbs=False)
    assert summary["status"] == "ok"

    after = hybrid_search(connection, query, settings, top_k=5)
    assert [r.chunk_id for r in after] == ids_before


def test_vectors_rebuild_does_not_mutate_embeddings(connection, fixture_vault: Path, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)
    snap = connection.execute(
        "SELECT chunk_id, vector_json FROM embeddings ORDER BY chunk_id"
    ).fetchall()
    payload = rebuild_chunk_vectors(connection)
    assert payload["status"] in {"ok", "skipped"}
    after = connection.execute(
        "SELECT chunk_id, vector_json FROM embeddings ORDER BY chunk_id"
    ).fetchall()
    assert [(int(r["chunk_id"]), r["vector_json"]) for r in snap] == [
        (int(r["chunk_id"]), r["vector_json"]) for r in after
    ]
