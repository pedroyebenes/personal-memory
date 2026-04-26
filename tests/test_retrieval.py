from __future__ import annotations

import json

from app.config import Settings
from app.ingest.register import ingest_vault
from app.models import SearchFilters
from app.retrieval.hybrid_search import hybrid_search
from app.retrieval.semantic_search import semantic_search


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
