from __future__ import annotations

import sqlite3

from app.config import Settings
from app.models import RetrievalResult
from app.retrieval.keyword_search import keyword_search
from app.retrieval.semantic_search import semantic_search


def hybrid_search(
    connection: sqlite3.Connection,
    query: str,
    settings: Settings,
    top_k: int = 5,
    semantic_weight: float = 0.7,
    keyword_weight: float = 0.3,
) -> list[RetrievalResult]:
    keyword_results = {result.chunk_id: result for result in keyword_search(connection, query, top_k=top_k * 2)}
    semantic_results = {result.chunk_id: result for result in semantic_search(connection, query, settings, top_k=top_k * 2)}

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
    merged.sort(key=lambda item: item.final_score, reverse=True)
    return merged[:top_k]
