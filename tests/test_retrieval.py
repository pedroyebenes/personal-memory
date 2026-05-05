from __future__ import annotations

import sqlite3

from app.config import Settings
from app.ingest.register import ingest_vault
from app.models import RetrievalResult, SearchFilters
import app.retrieval.hybrid_search as hybrid_module
from app.retrieval.hybrid_search import hybrid_search
from app.retrieval.semantic_search import semantic_search


def _insert_search_chunk(
    connection: sqlite3.Connection,
    source_path: str,
    title: str,
    text: str,
    *,
    tags: tuple[str, ...] = (),
) -> int:
    now = "2026-01-01T00:00:00+00:00"
    cursor = connection.execute(
        """
        INSERT INTO documents (
            source_path, title, raw_text, normalized_text, frontmatter_json,
            content_hash, last_modified, file_size, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, '{}', ?, ?, ?, ?, ?)
        """,
        (source_path, title, text, text, f"hash-{source_path}", now, len(text), now, now),
    )
    document_id = int(cursor.lastrowid)
    connection.executemany(
        "INSERT INTO document_tags (document_id, tag) VALUES (?, ?)",
        [(document_id, tag) for tag in tags],
    )
    chunk_cursor = connection.execute(
        """
        INSERT INTO chunks (
            document_id, chunk_index, section_title, text, heading_path_json,
            token_estimate, char_start, char_end, created_at
        )
        VALUES (?, 0, NULL, ?, '[]', 1, 0, ?, ?)
        """,
        (document_id, text, len(text), now),
    )
    connection.commit()
    return int(chunk_cursor.lastrowid)


def _candidate_result(chunk_id: int, score: float) -> RetrievalResult:
    return RetrievalResult(
        document_title=f"Candidate {chunk_id}",
        source_path=f"/tmp/candidate-{chunk_id}.md",
        chunk_id=chunk_id,
        chunk_index=0,
        section_title=None,
        snippet="",
        keyword_score=score,
        semantic_score=None,
        final_score=score,
    )


def test_semantic_search_result_shape(connection, fixture_vault, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)
    results = semantic_search(connection, "launch plan", settings, top_k=2)
    assert results
    result = results[0]
    assert isinstance(result.document_title, str)
    assert isinstance(result.source_path, str)
    assert result.semantic_score is not None


def test_hybrid_score_merge(connection, fixture_vault, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)
    results = hybrid_search(connection, "weekly review", settings, top_k=3)
    assert results
    assert any(result.keyword_score is not None for result in results)
    assert all(isinstance(result.final_score, float) for result in results)


def test_hybrid_search_filters_by_tag_and_alias(connection, fixture_vault, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)

    tag_filtered = hybrid_search(connection, "launch plan", settings, top_k=5, filters=SearchFilters(tags=("PROJECT",)))
    alias_filtered = hybrid_search(
        connection,
        "launch plan",
        settings,
        top_k=5,
        filters=SearchFilters(aliases=("north star",)),
    )

    assert tag_filtered
    assert all("project-note.md" in item.source_path for item in tag_filtered)
    assert alias_filtered
    assert all("project-note.md" in item.source_path for item in alias_filtered)


def test_hybrid_search_exposes_metadata_ranking_debug(connection, fixture_vault, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)

    results = hybrid_search(connection, "North Star", settings, top_k=3)

    assert results
    top = results[0]
    assert "project-note.md" in top.source_path
    assert top.metadata_score > 0
    assert top.score_explanation is not None
    assert "metadata_factors" in top.score_explanation
    assert top.score_explanation["final_score"] == top.final_score


def test_hybrid_search_prefers_chunk_whose_breadcrumb_matches_book_title(
    connection, tmp_path, settings: Settings
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    needle = "xyzneedle123 shared surface phrase for retrieval"
    (vault / "quijote.md").write_text(
        f"---\ntitle: Don Quijote\n---\n\n# Capítulo IV\n\n## De la aventura\n\n{needle}\n",
        encoding="utf-8",
    )
    (vault / "other.md").write_text(
        f"---\ntitle: Other Book\n---\n\n# Part One\n\n{needle}\n",
        encoding="utf-8",
    )
    ingest_vault(connection, vault, settings)

    results = hybrid_search(connection, "Don Quijote xyzneedle123", settings, top_k=5)
    assert results
    paths = [r.source_path for r in results]
    qi = next(i for i, p in enumerate(paths) if "quijote" in p.lower())
    ot = next((i for i, p in enumerate(paths) if "other" in p.lower()), None)
    if ot is not None:
        assert qi < ot


def test_hybrid_search_snippet_centers_matched_evidence(connection, tmp_path, settings: Settings) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    lead_in = " ".join(f"filler{i}" for i in range(120))
    (vault / "evidence.md").write_text(
        f"# Evidence\n\n{lead_in}\n\nNeedle evidence is the important sentence for retrieval quality.",
        encoding="utf-8",
    )
    ingest_vault(connection, vault, settings)

    results = hybrid_search(connection, "needle", settings, top_k=1)

    assert results
    assert "Needle evidence" in results[0].snippet
    assert "filler0" not in results[0].snippet


def test_hybrid_search_optional_reranking_adds_debug_score(connection, fixture_vault, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)

    results = hybrid_search(connection, "North Star", settings, top_k=3, use_rerank=True)

    assert results
    assert any(result.rerank_score > 0 for result in results)
    reranked = next(result for result in results if result.rerank_score > 0)
    assert reranked.score_explanation is not None
    assert reranked.score_explanation["rerank_score"] == reranked.rerank_score
    assert "rerank_factors" in reranked.score_explanation


def test_hybrid_search_reranking_can_be_enabled_from_settings(connection, fixture_vault, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)
    settings.enable_reranking = True

    results = hybrid_search(connection, "North Star", settings, top_k=3)

    assert results
    assert any(result.rerank_score > 0 for result in results)


def test_hybrid_search_widens_candidate_pool_before_filters(
    connection,
    settings: Settings,
    monkeypatch,
) -> None:
    chunk_ids = [
        _insert_search_chunk(connection, f"/tmp/distractor-{index}.md", f"Distractor {index}", "shared query")
        for index in range(5)
    ]
    target_id = _insert_search_chunk(
        connection,
        "/tmp/target.md",
        "Target",
        "shared query with the filtered evidence",
        tags=("project",),
    )
    ordered_ids = [*chunk_ids, target_id]
    assert ordered_ids.index(target_id) >= 2 * 2

    def fake_keyword_search(
        connection: sqlite3.Connection,
        query: str,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        return [_candidate_result(chunk_id, 0.8) for chunk_id in ordered_ids[:top_k]]

    monkeypatch.setattr(hybrid_module, "keyword_search", fake_keyword_search)
    monkeypatch.setattr(hybrid_module, "semantic_search", lambda *args, **kwargs: [])

    results = hybrid_search(
        connection,
        "shared query",
        settings,
        top_k=2,
        filters=SearchFilters(tags=("project",)),
        debug_scores=True,
    )

    assert [result.chunk_id for result in results] == [target_id]
    assert results[0].score_explanation is not None
    assert results[0].score_explanation["candidate_limit"] == 50
    assert results[0].score_explanation["candidate_count_before_filters"] == 6
    assert results[0].score_explanation["candidate_count_after_filters"] == 1


def test_hybrid_search_widened_pool_allows_rerank_to_promote_deep_candidate(
    connection,
    settings: Settings,
    monkeypatch,
) -> None:
    chunk_ids = [
        _insert_search_chunk(connection, f"/tmp/rerank-{index}.md", f"Rerank {index}", "generic text")
        for index in range(4)
    ]
    target_id = _insert_search_chunk(
        connection,
        "/tmp/rerank-target.md",
        "Rerank Target",
        "This chunk contains the needle phrase that should win after reranking.",
    )
    ordered_ids = [*chunk_ids, target_id]
    assert ordered_ids.index(target_id) >= 1 * 2
    scores = {
        chunk_id: score
        for chunk_id, score in zip(ordered_ids, (0.70, 0.68, 0.66, 0.64, 0.63), strict=True)
    }

    def fake_keyword_search(
        connection: sqlite3.Connection,
        query: str,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        return [_candidate_result(chunk_id, scores[chunk_id]) for chunk_id in ordered_ids[:top_k]]

    monkeypatch.setattr(hybrid_module, "keyword_search", fake_keyword_search)
    monkeypatch.setattr(hybrid_module, "semantic_search", lambda *args, **kwargs: [])

    results = hybrid_search(
        connection,
        "needle phrase",
        settings,
        top_k=1,
        use_rerank=True,
        debug_scores=True,
    )

    assert [result.chunk_id for result in results] == [target_id]
    assert results[0].rerank_score > 0
    assert results[0].score_explanation is not None
    assert results[0].score_explanation["candidate_limit"] == 50
