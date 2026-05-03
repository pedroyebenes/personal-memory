from __future__ import annotations

import json
import sqlite3

from app.config import Settings
from app.db import sqlite_vec_available, table_exists
from app.models import RetrievalResult
from app.processing.embeddings import cosine_similarity, embed_texts
from app.retrieval.snippets import extract_snippet


def _semantic_k_candidates(top_k: int) -> int:
    return min(500, max(50, top_k * 10))


def _distance_to_semantic_score(distance: float) -> float:
    score = 1.0 - float(distance)
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return score


def _semantic_search_scan(
    connection: sqlite3.Connection,
    query: str,
    query_vector: list[float],
    settings: Settings,
    top_k: int,
) -> list[RetrievalResult]:
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
                snippet=extract_snippet(row["text"], query),
                keyword_score=None,
                semantic_score=semantic_score,
                final_score=semantic_score,
            )
        )
    scored.sort(key=lambda item: item.final_score, reverse=True)
    return scored[:top_k]


def _semantic_search_ann(
    connection: sqlite3.Connection,
    query: str,
    query_vector: list[float],
    settings: Settings,
    top_k: int,
) -> list[RetrievalResult] | None:
    if not sqlite_vec_available(connection):
        return None
    if not table_exists(connection, "chunk_vectors"):
        return None
    count_row = connection.execute("SELECT COUNT(*) AS n FROM chunk_vectors").fetchone()
    if not count_row or int(count_row["n"]) == 0:
        return None
    try:
        from sqlite_vec import serialize_float32
    except ImportError:
        return None

    blob = serialize_float32(query_vector)
    k = _semantic_k_candidates(top_k)
    try:
        rows = connection.execute(
            """
            SELECT v.chunk_id, v.distance
            FROM chunk_vectors v
            WHERE v.embedding MATCH ?
              AND k = ?
            """,
            (blob, k),
        ).fetchall()
    except sqlite3.OperationalError:
        return None
    if not rows:
        return None

    chunk_ids_ordered = [int(r["chunk_id"]) for r in rows]
    distances = {int(r["chunk_id"]): float(r["distance"]) for r in rows}
    placeholders = ",".join("?" for _ in chunk_ids_ordered)
    detail_rows = connection.execute(
        f"""
        SELECT
            c.id AS chunk_id,
            c.chunk_index,
            c.section_title,
            c.text,
            d.title AS document_title,
            d.source_path
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        JOIN embeddings e ON e.chunk_id = c.id
        WHERE c.id IN ({placeholders})
          AND e.model_name = ?
        """,
        (*chunk_ids_ordered, settings.embedding_model_name),
    ).fetchall()
    details = {int(r["chunk_id"]): r for r in detail_rows}

    scored: list[RetrievalResult] = []
    for chunk_id in chunk_ids_ordered:
        if chunk_id not in details:
            continue
        row = details[chunk_id]
        dist = distances[chunk_id]
        sem = _distance_to_semantic_score(dist)
        scored.append(
            RetrievalResult(
                document_title=row["document_title"],
                source_path=row["source_path"],
                chunk_id=chunk_id,
                chunk_index=int(row["chunk_index"]),
                section_title=row["section_title"],
                snippet=extract_snippet(row["text"], query),
                keyword_score=None,
                semantic_score=sem,
                final_score=sem,
            )
        )
        if len(scored) >= top_k:
            break

    n_model = int(
        connection.execute(
            "SELECT COUNT(*) AS n FROM embeddings WHERE model_name = ?",
            (settings.embedding_model_name,),
        ).fetchone()["n"]
    )
    if len(scored) < min(top_k, n_model):
        return None
    return scored[:top_k]


def semantic_search_mode(connection: sqlite3.Connection) -> str:
    """Return 'ann' when sqlite-vec ANN is available and populated, 'scan' otherwise."""
    if not sqlite_vec_available(connection):
        return "scan"
    if not table_exists(connection, "chunk_vectors"):
        return "scan"
    count_row = connection.execute("SELECT COUNT(*) AS n FROM chunk_vectors").fetchone()
    if not count_row or int(count_row["n"]) == 0:
        return "scan"
    return "ann"


def semantic_search(connection: sqlite3.Connection, query: str, settings: Settings, top_k: int = 5) -> list[RetrievalResult]:
    query_vector = embed_texts([query], settings.embedding_model_name)[0]
    ann = _semantic_search_ann(connection, query, query_vector, settings, top_k)
    if ann is not None:
        return ann
    return _semantic_search_scan(connection, query, query_vector, settings, top_k)
