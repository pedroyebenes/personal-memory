from __future__ import annotations

import sqlite3

from app.config import Settings
from app.models import RetrievalResult, SearchFilters
from app.retrieval.keyword_search import keyword_search
from app.retrieval.semantic_search import semantic_search


def _normalize_filters(filters: SearchFilters | None) -> SearchFilters:
    return filters or SearchFilters()


def _load_chunk_metadata(connection: sqlite3.Connection, chunk_ids: set[int]) -> dict[int, dict[str, object]]:
    if not chunk_ids:
        return {}

    placeholders = ", ".join("?" for _ in chunk_ids)
    rows = connection.execute(
        f"""
        SELECT
            c.id AS chunk_id,
            d.source_path,
            d.last_modified,
            GROUP_CONCAT(DISTINCT dt.tag) AS tags,
            GROUP_CONCAT(DISTINCT da.alias) AS aliases
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        LEFT JOIN document_tags dt ON dt.document_id = d.id
        LEFT JOIN document_aliases da ON da.document_id = d.id
        WHERE c.id IN ({placeholders})
        GROUP BY c.id, d.source_path, d.last_modified
        """,
        tuple(chunk_ids),
    ).fetchall()
    metadata: dict[int, dict[str, object]] = {}
    for row in rows:
        metadata[int(row["chunk_id"])] = {
            "source_path": row["source_path"],
            "last_modified": row["last_modified"],
            "tags": {item.strip().lower() for item in str(row["tags"] or "").split(",") if item.strip()},
            "aliases": {item.strip().lower() for item in str(row["aliases"] or "").split(",") if item.strip()},
        }
    return metadata


def _matches_filters(result: RetrievalResult, filters: SearchFilters, metadata: dict[int, dict[str, object]]) -> bool:
    if not (filters.tags or filters.aliases or filters.path_prefix or filters.date_from or filters.date_to):
        return True
    item = metadata.get(result.chunk_id, {})
    result_path = str(item.get("source_path") or result.source_path)
    last_modified = str(item.get("last_modified") or "")
    item_tags = item.get("tags", set())
    item_aliases = item.get("aliases", set())

    if filters.path_prefix and not result_path.startswith(filters.path_prefix):
        return False
    if filters.date_from and last_modified < filters.date_from:
        return False
    if filters.date_to and last_modified > filters.date_to:
        return False
    if filters.tags and not set(filters.tags).issubset(item_tags):
        return False
    if filters.aliases and not set(filters.aliases).intersection(item_aliases):
        return False
    return True


def hybrid_search(
    connection: sqlite3.Connection,
    query: str,
    settings: Settings,
    top_k: int = 5,
    semantic_weight: float = 0.7,
    keyword_weight: float = 0.3,
    filters: SearchFilters | None = None,
) -> list[RetrievalResult]:
    filters = _normalize_filters(filters)
    keyword_results = {result.chunk_id: result for result in keyword_search(connection, query, top_k=top_k * 2)}
    semantic_results = {result.chunk_id: result for result in semantic_search(connection, query, settings, top_k=top_k * 2)}
    metadata = _load_chunk_metadata(connection, set(keyword_results) | set(semantic_results))

    merged: list[RetrievalResult] = []
    for chunk_id in set(keyword_results) | set(semantic_results):
        keyword_result = keyword_results.get(chunk_id)
        semantic_result = semantic_results.get(chunk_id)
        base = semantic_result or keyword_result
        assert base is not None
        keyword_score = keyword_result.keyword_score if keyword_result else None
        semantic_score = semantic_result.semantic_score if semantic_result else None
        final_score = (semantic_score or 0.0) * semantic_weight + (keyword_score or 0.0) * keyword_weight
        merged.append(
            RetrievalResult(
                document_title=base.document_title,
                source_path=base.source_path,
                chunk_id=base.chunk_id,
                chunk_index=base.chunk_index,
                section_title=base.section_title,
                snippet=base.snippet,
                keyword_score=keyword_score,
                semantic_score=semantic_score,
                final_score=final_score,
            )
        )
    merged = [item for item in merged if _matches_filters(item, filters, metadata)]
    merged.sort(key=lambda item: item.final_score, reverse=True)
    return merged[:top_k]
