from __future__ import annotations

import re
import sqlite3

from app.models import RetrievalResult


def _build_fts_query(query: str) -> str:
    terms = re.findall(r"[A-Za-z0-9_]+", query.lower())
    if not terms:
        return '""'
    return " OR ".join(f'"{term}"' for term in terms)


def keyword_search(connection: sqlite3.Connection, query: str, top_k: int = 5) -> list[RetrievalResult]:
    fts_query = _build_fts_query(query)
    rows = connection.execute(
        """
        SELECT
            c.id AS chunk_id,
            c.chunk_index,
            c.section_title,
            c.text,
            d.title AS document_title,
            d.source_path,
            bm25(chunks_fts) AS score
        FROM chunks_fts
        JOIN chunks c ON c.id = chunks_fts.chunk_id
        JOIN documents d ON d.id = c.document_id
        WHERE chunks_fts MATCH ?
        ORDER BY score
        LIMIT ?
        """,
        (fts_query, top_k),
    ).fetchall()

    results: list[RetrievalResult] = []
    for row in rows:
        keyword_score = 1.0 / (1.0 + max(float(row["score"]), 0.0))
        results.append(
            RetrievalResult(
                document_title=row["document_title"],
                source_path=row["source_path"],
                chunk_id=int(row["chunk_id"]),
                chunk_index=int(row["chunk_index"]),
                section_title=row["section_title"],
                snippet=row["text"][:280],
                keyword_score=keyword_score,
                semantic_score=None,
                final_score=keyword_score,
            )
        )
    return results
