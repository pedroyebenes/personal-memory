from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.ingest.register import ingest_vault
from app.processing.concepts import (
    fold_plural_key,
    is_acronym_source,
    normalize_key,
)
from app.retrieval.concept_search import find_concepts_for_terms


def test_plural_fold_skips_when_base_not_in_pool() -> None:
    assert fold_plural_key("classes", {"classes"}, source_is_acronym=False) == "classes"
    assert fold_plural_key("classes", {"classes", "class"}, source_is_acronym=False) == "class"


def test_plural_fold_skips_acronyms() -> None:
    assert fold_plural_key("llms", {"llm", "llms"}, source_is_acronym=True) == "llms"


def test_is_acronym_source_heuristic() -> None:
    assert is_acronym_source("NASA") is True
    assert is_acronym_source("Project Atlas") is False


def test_ingest_merges_diacritic_variants(connection, tmp_path: Path, settings: Settings) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "a.md").write_text(
        "---\ntitle: Travel Log\n---\n\n# Note\n\nVisit [[México]] and [[Mexico]].\n",
        encoding="utf-8",
    )
    ingest_vault(connection, vault, settings)
    rows = connection.execute(
        "SELECT id, normalized_key, mention_count FROM entities WHERE normalized_key = ?",
        ("mexico",),
    ).fetchall()
    assert len(rows) == 1
    assert int(rows[0]["mention_count"]) >= 2


def test_ingest_folds_plural_when_base_appears_same_document(
    connection, tmp_path: Path, settings: Settings
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "book.md").write_text(
        "# Book\n\nCompare [[Widget]] with [[Widgets]] in the margin.\n",
        encoding="utf-8",
    )
    ingest_vault(connection, vault, settings)
    row = connection.execute(
        "SELECT id, mention_count FROM entities WHERE normalized_key = ?",
        (normalize_key("Widget"),),
    ).fetchone()
    assert row is not None
    assert int(row["mention_count"]) >= 2


def test_find_concepts_for_terms_empty_for_stopword_only_query(connection, fixture_vault: Path, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)
    assert find_concepts_for_terms(connection, ["the", "and"]) == []
