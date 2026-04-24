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

    tag_filtered = hybrid_search(connection, "launch plan", settings, top_k=5, filters=SearchFilters(tags=("project",)))
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
