from __future__ import annotations

import re
import sqlite3

from app.models import RetrievalResult
from app.retrieval.snippets import extract_snippet

# Align with indexed column order: document_title, section_title, text (chunk_id is UNINDEXED).
BM25_WEIGHT_TITLE = 3.0
BM25_WEIGHT_SECTION = 5.0
BM25_WEIGHT_TEXT = 1.0


def _fts_terms(query: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_]+", query.lower())


def _build_fts_query(query: str) -> str:
    terms = _fts_terms(query)
    if not terms:
        return '""'
    quoted = [f'"{term}"' for term in terms]
    or_clause = " OR ".join(quoted)
    if len(terms) < 2:
        return or_clause
    near_body = " ".join(quoted)
    near_clause = f"NEAR({near_body}, 5)"
    return f"( {near_clause} ) OR ( {or_clause} )"


def keyword_search(connection: sqlite3.Connection, query: str, top_k: int = 5) -> list[RetrievalResult]:
    fts_query = _build_fts_query(query)
    rows = connection.execute(
        f"""
        SELECT
            c.id AS chunk_id,
            c.chunk_index,
            c.section_title,
            c.text,
            d.title AS document_title,
            d.source_path,
            bm25(chunks_fts, ?, ?, ?) AS score
        FROM chunks_fts
        JOIN chunks c ON c.id = chunks_fts.chunk_id
        JOIN documents d ON d.id = c.document_id
        WHERE chunks_fts MATCH ?
        ORDER BY score
        LIMIT ?
        """,
        (
            BM25_WEIGHT_TITLE,
            BM25_WEIGHT_SECTION,
            BM25_WEIGHT_TEXT,
            fts_query,
            top_k,
        ),
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
                snippet=extract_snippet(row["text"], query),
                keyword_score=keyword_score,
                semantic_score=None,
                final_score=keyword_score,
            )
        )
    return results
