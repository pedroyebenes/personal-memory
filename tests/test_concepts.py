from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import Settings
from app.db import connect, init_db
from app.ingest.register import ingest_vault, reclassify_entities, refresh_concepts, reindex_vault
from app.models import ChunkRecord, ParsedDocument
from app.processing.concepts import (
    classify_entity_type,
    extract_concept_mentions,
    normalize_key,
)
from app.retrieval.concept_search import (
    chunks_with_concepts,
    concept_noise_report,
    find_concept,
    find_concepts_for_terms,
    get_concept_detail,
    list_concepts,
)
from app.retrieval.hybrid_search import hybrid_search


def _make_chunk(index: int, section: str | None, text: str) -> ChunkRecord:
    return ChunkRecord(
        chunk_index=index,
        section_title=section,
        text=text,
        token_estimate=len(text.split()),
        char_start=0,
        char_end=len(text),
    )


def _doc(path: Path, *, title: str, tags=None, aliases=None) -> ParsedDocument:
    return ParsedDocument(
        source_path=path,
        title=title,
        raw_text="",
        normalized_text="",
        frontmatter={},
        tags=list(tags or []),
        aliases=list(aliases or []),
    )


def test_normalize_key_collapses_case_and_separators() -> None:
    assert normalize_key("Project_North-Star") == "project north star"
    assert normalize_key("  Multi  Space  ") == "multi space"
    assert normalize_key("UPPER") == "upper"


def test_classify_entity_type_splits_structures_from_concepts() -> None:
    assert classify_entity_type("CAPÍTULO XL", "heading") == "structure"
    assert classify_entity_type("Capítulo XLII. Que trata de la venta", "heading") == "structure"
    assert classify_entity_type("Capítulo IV: Donde se cuenta la estraña aventura", "heading") == "structure"
    assert classify_entity_type("Chapter 3 — The Road Home", "heading") == "structure"
    assert classify_entity_type("Prólogo", "heading") == "structure"
    assert classify_entity_type("Parte Primera", "heading") == "structure"
    assert classify_entity_type("2026-04-20", "title") == "structure"
    assert classify_entity_type("2026/04/20", "title") == "structure"
    assert classify_entity_type("April 20, 2026", "title") == "structure"
    assert classify_entity_type("20 abril 2026", "title") == "structure"
    assert classify_entity_type("Monday", "heading") == "structure"
    assert classify_entity_type("lunes", "heading") == "structure"
    assert classify_entity_type("2", "heading") == "structure"
    assert classify_entity_type("IV", "heading") == "structure"
    assert classify_entity_type("Text/intro2.xhtml", "heading") == "structure"
    assert classify_entity_type("Project North Star", "heading") == "concept"
    assert classify_entity_type("Dulcinea del Toboso", "heading") == "concept"
    assert classify_entity_type("CAPÍTULO XL", "tag") == "concept"
    assert classify_entity_type("Capítulo I", "alias") == "structure"
    assert classify_entity_type("North Star", "alias") == "concept"


def test_init_db_migrates_nonempty_legacy_entities(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.sqlite3"
    connection = connect(db_path)
    try:
        connection.execute(
            """
            CREATE TABLE entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_name TEXT NOT NULL,
                entity_type TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO entities (canonical_name, entity_type, metadata_json, created_at)
            VALUES ('Legacy Concept', 'concept', '{}', '2024-01-01T00:00:00+00:00')
            """
        )
        connection.commit()

        init_db(connection)

        row = connection.execute(
            "SELECT canonical_name, normalized_key, mention_count FROM entities WHERE normalized_key = ?",
            ("legacy concept",),
        ).fetchone()
        assert row is not None
        assert row["canonical_name"] == "Legacy Concept"
        assert int(row["mention_count"]) == 0
    finally:
        connection.close()


def test_extract_concept_mentions_covers_all_sources(tmp_path: Path) -> None:
    chunks = [
        _make_chunk(0, "Overview", "Body refers to [[Project North Star]] briefly."),
        _make_chunk(1, "Implementation Plan", "More about [[Project North Star|the launch]]."),
    ]
    parsed = _doc(
        tmp_path / "project_north_star.md",
        title="Project North Star",
        tags=["project", "planning"],
        aliases=["North Star", "Launch Plan"],
    )
    mentions = extract_concept_mentions(parsed, chunks)

    by_method: dict[str, list[str]] = {}
    for mention in mentions:
        by_method.setdefault(mention.extraction_method, []).append(mention.normalized_key)

    assert "project north star" in by_method["title"]
    # filename normalized matches title; the extractor suppresses the duplicate filename concept
    assert "filename" not in by_method
    assert {"project", "planning"} <= set(by_method["tag"])
    # Aliases anchor to the title's normalized key.
    assert by_method["alias"] == ["project north star", "project north star"]
    assert "project north star" in by_method["wikilink"]
    assert {"overview", "implementation plan"} == set(by_method["heading"])
    assert {mention.entity_type for mention in mentions} == {"concept"}


def test_extract_concept_mentions_splits_structural_alias_from_title(tmp_path: Path) -> None:
    chunks = [_make_chunk(0, None, "Body.")]
    parsed = _doc(
        tmp_path / "quijote.md",
        title="El Quijote",
        aliases=["Capítulo I", "Don Quijote"],
    )
    mentions = extract_concept_mentions(parsed, chunks)
    by_key_method = {(m.normalized_key, m.extraction_method): m.entity_type for m in mentions}

    assert by_key_method[("el quijote", "title")] == "concept"
    assert by_key_method[("capítulo i", "alias")] == "structure"
    assert by_key_method[("el quijote", "alias")] == "concept"


def test_extract_concept_mentions_marks_structural_headings(tmp_path: Path) -> None:
    chunks = [
        _make_chunk(0, "CAPÍTULO XL", "Chapter text."),
        _make_chunk(1, "Research Agenda", "Semantic section."),
    ]
    parsed = _doc(tmp_path / "2026-04-20.md", title="2026-04-20")
    mentions = extract_concept_mentions(parsed, chunks)

    by_key = {mention.normalized_key: mention.entity_type for mention in mentions}

    assert by_key["2026 04 20"] == "structure"
    assert by_key["capítulo xl"] == "structure"
    assert by_key["research agenda"] == "concept"


def test_extract_concept_mentions_adds_body_text_candidates(tmp_path: Path) -> None:
    chunks = [
        _make_chunk(
            0,
            "Notes",
            (
                "Project Atlas is the planning system for research notes. "
                "The team uses **retrieval quality** reviews and #research/llms tags."
            ),
        ),
        _make_chunk(
            1,
            "Followups",
            "Project Atlas depends on OpenAI API traces. OpenAI API traces guide evaluation.",
        ),
    ]
    parsed = _doc(tmp_path / "meeting.md", title="Meeting Notes")

    mentions = extract_concept_mentions(parsed, chunks)
    by_method: dict[str, set[str]] = {}
    for mention in mentions:
        by_method.setdefault(mention.extraction_method, set()).add(mention.normalized_key)

    assert "project atlas" in by_method["definition"]
    assert "retrieval quality" in by_method["emphasis"]
    assert "research llms" in by_method["inline_tag"]
    assert "project atlas" in by_method["body_phrase"]
    assert "openai api" in by_method["body_phrase"]
    assert all(mention.entity_type == "concept" for mention in mentions if mention.extraction_method in {"definition", "emphasis", "inline_tag", "body_phrase"})


def test_definition_extraction_accepts_spanish_markers(tmp_path: Path) -> None:
    chunks = [_make_chunk(0, "Notas", "Dulcinea Toboso es una figura idealizada en la novela.")]
    parsed = _doc(tmp_path / "book.md", title="Book")

    mentions = extract_concept_mentions(parsed, chunks)
    definition_keys = {
        mention.normalized_key
        for mention in mentions
        if mention.extraction_method == "definition"
    }

    assert "dulcinea toboso" in definition_keys


def test_body_phrase_extraction_requires_repeated_evidence(tmp_path: Path) -> None:
    chunks = [
        _make_chunk(0, "Notes", "Single Mention appears only once."),
        _make_chunk(1, "Followups", "Different Topic appears only once too."),
    ]
    parsed = _doc(tmp_path / "meeting.md", title="Meeting Notes")

    mentions = extract_concept_mentions(parsed, chunks)
    body_keys = {
        mention.normalized_key
        for mention in mentions
        if mention.extraction_method == "body_phrase"
    }

    assert "single mention" not in body_keys
    assert "different topic" not in body_keys


def test_body_text_extraction_filters_structures_and_stopwords(tmp_path: Path) -> None:
    chunks = [
        _make_chunk(
            0,
            "Body",
            "CAPÍTULO XL is a heading. CAPÍTULO XL appears again. **the** is ignored.",
        )
    ]
    parsed = _doc(tmp_path / "book.md", title="Book")

    mentions = extract_concept_mentions(parsed, chunks)
    body_keys = {
        mention.normalized_key
        for mention in mentions
        if mention.extraction_method in {"body_phrase", "emphasis", "definition"}
    }

    assert "capítulo xl" not in body_keys
    assert "the" not in body_keys


def test_extract_concept_mentions_preserves_filename_when_distinct(tmp_path: Path) -> None:
    chunks = [_make_chunk(0, None, "Body.")]
    parsed = _doc(tmp_path / "project_north_star.md", title="Untitled")
    mentions = extract_concept_mentions(parsed, chunks)
    methods = {mention.extraction_method for mention in mentions}
    assert "filename" in methods


def test_ingest_populates_entities_and_mentions(connection, fixture_vault: Path, settings: Settings) -> None:
    summary = ingest_vault(connection, fixture_vault, settings)

    assert summary["status"] == "completed"
    rows = connection.execute(
        "SELECT canonical_name, normalized_key, mention_count FROM entities ORDER BY normalized_key"
    ).fetchall()
    keys = {row["normalized_key"] for row in rows}
    # title concepts
    assert "project north star" in keys
    assert "linked ideas" in keys
    # tag concepts
    assert "project" in keys
    assert "research" in keys
    # heading concepts
    assert "overview" in keys
    # alias mention should reuse the project north star entity
    project = connection.execute(
        "SELECT id, mention_count FROM entities WHERE normalized_key = 'project north star'"
    ).fetchone()
    methods = connection.execute(
        "SELECT DISTINCT extraction_method FROM entity_mentions WHERE entity_id = ?",
        (int(project["id"]),),
    ).fetchall()
    assert {row["extraction_method"] for row in methods} >= {"title", "alias", "wikilink"}
    assert int(project["mention_count"]) >= 3


def test_ingest_populates_body_text_concepts_with_provenance(connection, tmp_path: Path, settings: Settings) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "meeting.md").write_text(
        (
            "# Meeting Notes\n\n"
            "Project Atlas is the planning system for research notes. "
            "The team uses **retrieval quality** reviews and #research/llms tags.\n\n"
            "## Followups\n\n"
            "Project Atlas depends on OpenAI API traces. OpenAI API traces guide evaluation.\n"
        ),
        encoding="utf-8",
    )

    ingest_vault(connection, vault, settings)

    atlas = find_concept(connection, name="Project Atlas")
    assert atlas is not None
    detail = get_concept_detail(connection, int(atlas["id"]))
    assert detail is not None
    methods = {mention["extraction_method"] for mention in detail["mentions"]}
    assert {"definition", "body_phrase"} <= methods
    assert all(mention["chunk_id"] > 0 for mention in detail["mentions"])

    quality = find_concept(connection, name="retrieval quality")
    assert quality is not None
    tag = find_concept(connection, name="research llms")
    assert tag is not None


def test_changed_document_refresh_does_not_disturb_unrelated_mentions(
    connection, tmp_path: Path, fixture_vault: Path, settings: Settings
) -> None:
    vault_copy = tmp_path / "vault"
    vault_copy.mkdir()
    for source in fixture_vault.iterdir():
        (vault_copy / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    ingest_vault(connection, vault_copy, settings)

    plain_mention_ids = {
        int(row["id"])
        for row in connection.execute(
            """
            SELECT em.id
            FROM entity_mentions em
            JOIN chunks c ON c.id = em.chunk_id
            JOIN documents d ON d.id = c.document_id
            WHERE d.source_path LIKE '%plain-note.md'
            """
        ).fetchall()
    }
    assert plain_mention_ids

    # Modify only the project note and re-ingest.
    project_note = vault_copy / "project-note.md"
    project_note.write_text(project_note.read_text(encoding="utf-8") + "\n\n## Followups\n\nMore detail.\n", encoding="utf-8")
    import os
    bumped = project_note.stat().st_mtime + 100
    os.utime(project_note, (bumped, bumped))

    summary = ingest_vault(connection, vault_copy, settings)
    assert summary["indexed"] == 1
    assert summary["skipped"] == 2

    surviving_ids = {
        int(row["id"])
        for row in connection.execute(
            """
            SELECT em.id
            FROM entity_mentions em
            JOIN chunks c ON c.id = em.chunk_id
            JOIN documents d ON d.id = c.document_id
            WHERE d.source_path LIKE '%plain-note.md'
            """
        ).fetchall()
    }
    assert plain_mention_ids == surviving_ids


def test_reindex_rebuilds_concepts_cleanly(connection, fixture_vault: Path, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)
    before = connection.execute("SELECT id, mention_count FROM entities ORDER BY id").fetchall()
    before_ids = {int(row["id"]) for row in before}

    reindex_vault(connection, fixture_vault, settings)
    after = connection.execute("SELECT id, mention_count FROM entities ORDER BY id").fetchall()
    # Entity IDs should be regenerated (rows fully wiped) but the same canonical concepts should reappear.
    after_keys = {
        row["normalized_key"]
        for row in connection.execute("SELECT normalized_key FROM entities").fetchall()
    }
    before_keys = {
        row["normalized_key"]
        for row in connection.execute(
            "SELECT normalized_key FROM entities WHERE id IN ({})".format(
                ",".join(str(i) for i in before_ids) or "NULL"
            )
        ).fetchall()
    }
    # The previous-id-set query returns nothing post-reindex (rows are gone). The set of
    # concepts after reindex should still cover all the keys we saw before.
    assert before_keys == set()
    assert "project north star" in after_keys
    assert all(int(row["mention_count"]) > 0 for row in after)


def test_pruned_document_removes_its_concepts(connection, tmp_path: Path, settings: Settings) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "kept.md").write_text("---\ntags: [keep]\n---\n# Kept\n\nBody.", encoding="utf-8")
    removed = vault / "removed.md"
    removed.write_text("---\ntags: [throwaway]\n---\n# Removed\n\nBody.", encoding="utf-8")

    ingest_vault(connection, vault, settings)
    keys_before = {
        row["normalized_key"]
        for row in connection.execute("SELECT normalized_key FROM entities").fetchall()
    }
    assert {"throwaway", "removed"} <= keys_before

    removed.unlink()
    summary = ingest_vault(connection, vault, settings)
    assert summary["pruned_entities"] >= 2  # 'throwaway' tag + 'removed' title

    keys_after = {
        row["normalized_key"]
        for row in connection.execute("SELECT normalized_key FROM entities").fetchall()
    }
    assert "throwaway" not in keys_after
    assert "removed" not in keys_after
    assert "keep" in keys_after


def test_list_concepts_returns_aggregated_metadata(connection, fixture_vault: Path, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)

    concepts = list_concepts(connection, limit=100)

    assert concepts
    project = next(item for item in concepts if item["normalized_key"] == "project north star")
    assert project["mention_count"] >= 3
    assert project["document_count"] >= 1
    assert "title" in project["extraction_methods"]
    assert "alias" in project["extraction_methods"]
    assert project["quality"] == "strong"


def test_list_concepts_filters_by_method_and_quality(connection, fixture_vault: Path, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)

    alias_items = list_concepts(connection, method="alias", limit=100)
    strong_items = list_concepts(connection, quality="strong", limit=100)

    assert alias_items
    assert all("alias" in item["extraction_methods"] for item in alias_items)
    assert strong_items
    assert all(item["quality"] == "strong" for item in strong_items)


def test_list_concepts_search_filters_by_substring(connection, fixture_vault: Path, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)

    matches = list_concepts(connection, search="north", limit=20)

    assert matches
    assert all("north" in item["normalized_key"] or "North" in item["canonical_name"] for item in matches)


def test_list_concepts_defaults_to_semantic_concepts(connection, tmp_path: Path, settings: Settings) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "chapter.md").write_text(
        "# CAPÍTULO XL\n\nBody mentions [[Project North Star]].\n\n## Research Agenda\n\nNotes.",
        encoding="utf-8",
    )
    ingest_vault(connection, vault, settings)

    default_items = list_concepts(connection, limit=100)
    structure_items = list_concepts(connection, entity_type="structure", limit=100)
    all_items = list_concepts(connection, entity_type=None, limit=100)

    assert all(item["entity_type"] == "concept" for item in default_items)
    assert "capítulo xl" not in {item["normalized_key"] for item in default_items}
    assert "capítulo xl" in {item["normalized_key"] for item in structure_items}
    assert "capítulo xl" in {item["normalized_key"] for item in all_items}


def test_get_concept_detail_returns_chunk_provenance(connection, fixture_vault: Path, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)
    concept = find_concept(connection, name="Project North Star")
    assert concept is not None

    detail = get_concept_detail(connection, int(concept["id"]))

    assert detail is not None
    assert detail["mention_count"] >= 3
    assert detail["mentions"]
    for mention in detail["mentions"]:
        assert mention["chunk_id"] > 0
        assert mention["document_id"] > 0
        assert mention["source_path"].endswith(".md")
    assert detail["documents"]
    assert detail["documents"][0]["mention_count"] >= 1
    assert detail["related_documents"] == detail["documents"]
    assert detail["top_chunks"]
    assert "source_ref" in detail["top_chunks"][0]
    assert "markdown_ref" in detail["top_chunks"][0]


def test_concept_noise_report_flags_one_off_medium_concepts(connection, tmp_path: Path, settings: Settings) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "scratch.md").write_text("# Scratch Idea\n\nBody.", encoding="utf-8")
    ingest_vault(connection, vault, settings)

    report = concept_noise_report(connection, limit=10)

    assert report["count"] >= 1
    assert any(item["normalized_key"] == "scratch idea" for item in report["concepts"])


def test_find_concept_returns_none_for_unknown(connection) -> None:
    assert find_concept(connection, name="nothing here") is None
    assert find_concept(connection, concept_id=99999) is None


def test_find_concept_resolves_frontmatter_alias(connection, fixture_vault: Path, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)

    concept = find_concept(connection, name="North Star")

    assert concept is not None
    assert concept["normalized_key"] == "project north star"


def test_refresh_concepts_rebuilds_from_existing_chunks(connection, fixture_vault: Path, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)

    # Tamper: clear the derived layer manually as if it had become stale.
    connection.execute("DELETE FROM entity_mentions")
    connection.execute("DELETE FROM entities")
    connection.commit()

    result = refresh_concepts(connection)

    assert result["documents"] == 3
    assert result["mentions"] > 0
    assert result["entities"] > 0
    keys = {
        row["normalized_key"]
        for row in connection.execute("SELECT normalized_key FROM entities").fetchall()
    }
    assert "project north star" in keys


def test_refresh_concepts_is_idempotent_for_body_text_mentions(connection, tmp_path: Path, settings: Settings) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "meeting.md").write_text(
        (
            "# Meeting Notes\n\n"
            "Project Atlas is the planning system. Project Atlas improves retrieval quality. "
            "**retrieval quality** is reviewed weekly. #research/llms\n"
        ),
        encoding="utf-8",
    )
    ingest_vault(connection, vault, settings)

    first = refresh_concepts(connection)
    first_rows = connection.execute(
        """
        SELECT e.normalized_key, em.extraction_method, c.chunk_index
        FROM entity_mentions em
        JOIN entities e ON e.id = em.entity_id
        JOIN chunks c ON c.id = em.chunk_id
        ORDER BY e.normalized_key, em.extraction_method, c.chunk_index
        """
    ).fetchall()

    second = refresh_concepts(connection)
    second_rows = connection.execute(
        """
        SELECT e.normalized_key, em.extraction_method, c.chunk_index
        FROM entity_mentions em
        JOIN entities e ON e.id = em.entity_id
        JOIN chunks c ON c.id = em.chunk_id
        ORDER BY e.normalized_key, em.extraction_method, c.chunk_index
        """
    ).fetchall()

    assert second["mentions"] == first["mentions"]
    assert [tuple(row) for row in second_rows] == [tuple(row) for row in first_rows]


def test_concept_boost_surfaces_in_score_explanation(connection, fixture_vault: Path, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)

    boosted = hybrid_search(connection, "north star", settings, top_k=5, use_concept_boost=True)
    plain = hybrid_search(connection, "north star", settings, top_k=5, use_concept_boost=False)

    assert boosted, "expected results when boosting"
    assert plain, "expected results without boost"

    boosted_top = boosted[0]
    plain_top = next(item for item in plain if item.chunk_id == boosted_top.chunk_id)
    assert boosted_top.final_score >= plain_top.final_score
    assert boosted_top.score_explanation
    assert "concept_boost" in boosted_top.score_explanation
    matches = boosted_top.score_explanation.get("concept_matches") or []
    assert any(item["canonical_name"].lower().startswith("project") for item in matches)


def test_find_concepts_for_terms_returns_aliased_entities(connection, fixture_vault: Path, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)

    matches = find_concepts_for_terms(connection, ["Project", "North", "Star"])

    keys = {item["normalized_key"] for item in matches}
    # Phrase candidates and alias mentions should resolve the canonical project concept.
    assert "project north star" in keys
    # "project" and "project north star" both exist; tokens individually match the tag concept "project".
    assert "project" in keys


def test_reclassify_entities_is_idempotent_and_preserves_mentions(
    connection, tmp_path: Path, settings: Settings
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "daily.md").write_text("# Monday\n\nNotes.\n", encoding="utf-8")
    ingest_vault(connection, vault, settings)
    row = connection.execute("SELECT id FROM entities WHERE normalized_key = 'monday'").fetchone()
    assert row is not None
    connection.execute("UPDATE entities SET entity_type = 'concept' WHERE id = ?", (int(row["id"]),))
    connection.commit()

    mentions_before = connection.execute(
        "SELECT entity_id, chunk_id, mention_text, extraction_method FROM entity_mentions ORDER BY id"
    ).fetchall()

    first = reclassify_entities(connection)
    assert first["entities_updated"] >= 1
    et = connection.execute("SELECT entity_type FROM entities WHERE id = ?", (int(row["id"]),)).fetchone()[
        "entity_type"
    ]
    assert et == "structure"

    second = reclassify_entities(connection)
    assert second["entities_updated"] == 0

    mentions_after = connection.execute(
        "SELECT entity_id, chunk_id, mention_text, extraction_method FROM entity_mentions ORDER BY id"
    ).fetchall()
    assert [tuple(r) for r in mentions_after] == [tuple(r) for r in mentions_before]


def test_find_concepts_for_terms_ignores_structures(connection, tmp_path: Path, settings: Settings) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "chapter.md").write_text("# CAPÍTULO XL\n\nBody.", encoding="utf-8")
    ingest_vault(connection, vault, settings)

    matches = find_concepts_for_terms(connection, ["capítulo", "xl"])

    assert matches == []


def test_chunks_with_concepts_filters_to_known_chunks(connection, fixture_vault: Path, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)

    project = find_concept(connection, name="Project North Star")
    assert project is not None
    chunk_ids = {
        int(row["id"])
        for row in connection.execute("SELECT id FROM chunks").fetchall()
    }
    matches = chunks_with_concepts(connection, chunk_ids, {int(project["id"])})

    assert matches
    assert all(int(project["id"]) in entities for entities in matches.values())
