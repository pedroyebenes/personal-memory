from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.db import sqlite_vec_available, table_exists
from app.ingest.register import ingest_vault
from app.processing.embeddings import embed_texts
from app.retrieval.semantic_search import _semantic_search_scan, semantic_search


def test_semantic_search_empty_db_no_chunks(connection, settings: Settings) -> None:
    assert semantic_search(connection, "anything", settings, top_k=5) == []


def test_semantic_ann_top_k_chunk_ids_match_full_scan(
    connection,
    fixture_vault: Path,
    settings: Settings,
) -> None:
    if not sqlite_vec_available(connection):
        pytest.skip("sqlite-vec extension not loaded")
    ingest_vault(connection, fixture_vault, settings)
    if not table_exists(connection, "chunk_vectors"):
        pytest.skip("chunk_vectors table not present after ingest")

    query = "weekly review"
    top_k = 12
    query_vector = embed_texts([query], settings.embedding_model_name)[0]
    scan_results = _semantic_search_scan(connection, query, query_vector, settings, top_k)
    ann_results = semantic_search(connection, query, settings, top_k=top_k)
    assert [r.chunk_id for r in ann_results] == [r.chunk_id for r in scan_results]


def test_dual_write_chunk_vectors_row_count_matches_embeddings(
    connection,
    fixture_vault: Path,
    settings: Settings,
) -> None:
    if not sqlite_vec_available(connection):
        pytest.skip("sqlite-vec extension not loaded")
    ingest_vault(connection, fixture_vault, settings)
    if not table_exists(connection, "chunk_vectors"):
        pytest.skip("chunk_vectors table not present after ingest")
    emb_n = int(connection.execute("SELECT COUNT(*) AS n FROM embeddings").fetchone()["n"])
    vec_n = int(connection.execute("SELECT COUNT(*) AS n FROM chunk_vectors").fetchone()["n"])
    assert vec_n == emb_n


def test_reingest_prunes_stale_chunk_vectors(
    connection,
    tmp_path: Path,
    settings: Settings,
) -> None:
    if not sqlite_vec_available(connection):
        pytest.skip("sqlite-vec extension not loaded")
    vault = tmp_path / "v"
    vault.mkdir()
    note = vault / "a.md"
    note.write_text("# One\n\nalpha beta gamma.\n", encoding="utf-8")
    ingest_vault(connection, vault, settings)
    if not table_exists(connection, "chunk_vectors"):
        pytest.skip("chunk_vectors table not present after ingest")
    note.write_text("# One\n\nonly one paragraph now.\n", encoding="utf-8")
    ingest_vault(connection, vault, settings)
    emb_ids = {
        int(r["chunk_id"])
        for r in connection.execute("SELECT chunk_id FROM embeddings").fetchall()
    }
    vec_ids = {
        int(r["chunk_id"])
        for r in connection.execute("SELECT chunk_id FROM chunk_vectors").fetchall()
    }
    assert vec_ids == emb_ids
    for cid in vec_ids:
        assert connection.execute("SELECT 1 FROM embeddings WHERE chunk_id = ?", (cid,)).fetchone() is not None
