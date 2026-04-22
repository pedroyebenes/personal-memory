from __future__ import annotations

import json
import sqlite3

from app.config import Settings
from app.models import RetrievalResult
from app.processing.embeddings import cosine_similarity, embed_texts


def semantic_search(connection: sqlite3.Connection, query: str, settings: Settings, top_k: int = 5) -> list[RetrievalResult]:
    query_vector = embed_texts([query], settings.embedding_model_name)[0]
    rows = connection.execute(
        """
        SELECT
            c.id AS chunk_id,
            c.chunk_index,
            c.section_title,
            c.text,
            d.title AS document_title,
            d.source_path,
            e.vector_json
        FROM embeddings e
        JOIN chunks c ON c.id = e.chunk_id
        JOIN documents d ON d.id = c.document_id
        WHERE e.model_name = ?
        """,
        (settings.embedding_model_name,),
    ).fetchall()

    scored: list[RetrievalResult] = []
    for row in rows:
        semantic_score = cosine_similarity(query_vector, json.loads(row["vector_json"]))
        scored.append(
            RetrievalResult(
                document_title=row["document_title"],
                source_path=row["source_path"],
                chunk_id=int(row["chunk_id"]),
                chunk_index=int(row["chunk_index"]),
                section_title=row["section_title"],
                snippet=row["text"][:280],
                keyword_score=None,
                semantic_score=semantic_score,
                final_score=semantic_score,
            )
        )
    scored.sort(key=lambda item: item.final_score, reverse=True)
    return scored[:top_k]
