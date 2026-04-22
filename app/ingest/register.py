from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.config import Settings
from app.models import ChunkRecord, ParsedDocument
from app.processing.chunker import chunk_document
from app.processing.embeddings import embed_texts
from app.util.hashing import sha256_text
from app.util.logging import get_logger
from app.util.timestamps import utc_now_iso
from app.vault.obsidian_parser import parse_markdown_file
from app.vault.scanner import scan_markdown_files

LOGGER = get_logger(__name__)


def _get_document_row(connection: sqlite3.Connection, source_path: str) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM documents WHERE source_path = ?", (source_path,)).fetchone()


def _record_run(
    connection: sqlite3.Connection,
    run_type: str,
    vault_path: Path,
    status: str,
    document_count: int = 0,
    run_id: int | None = None,
) -> int:
    if run_id is None:
        cursor = connection.execute(
            """
            INSERT INTO ingestion_runs (run_type, vault_path, status, document_count, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_type, str(vault_path), status, document_count, utc_now_iso()),
        )
        connection.commit()
        return int(cursor.lastrowid)
    connection.execute(
        """
        UPDATE ingestion_runs
        SET status = ?, document_count = ?, completed_at = ?
        WHERE id = ?
        """,
        (status, document_count, utc_now_iso(), run_id),
    )
    connection.commit()
    return run_id


def _upsert_document(
    connection: sqlite3.Connection,
    parsed: ParsedDocument,
    content_hash: str,
    last_modified: str,
) -> int:
    now = utc_now_iso()
    existing = _get_document_row(connection, str(parsed.source_path))
    if existing is None:
        cursor = connection.execute(
            """
            INSERT INTO documents (
                source_path, title, raw_text, normalized_text, frontmatter_json,
                content_hash, last_modified, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(parsed.source_path),
                parsed.title,
                parsed.raw_text,
                parsed.normalized_text,
                json.dumps(parsed.frontmatter, sort_keys=True),
                content_hash,
                last_modified,
                now,
                now,
            ),
        )
        document_id = int(cursor.lastrowid)
    else:
        document_id = int(existing["id"])
        connection.execute(
            """
            UPDATE documents
            SET title = ?, raw_text = ?, normalized_text = ?, frontmatter_json = ?,
                content_hash = ?, last_modified = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                parsed.title,
                parsed.raw_text,
                parsed.normalized_text,
                json.dumps(parsed.frontmatter, sort_keys=True),
                content_hash,
                last_modified,
                now,
                document_id,
            ),
        )

    connection.execute("DELETE FROM document_tags WHERE document_id = ?", (document_id,))
    connection.execute("DELETE FROM document_aliases WHERE document_id = ?", (document_id,))
    connection.executemany(
        "INSERT OR IGNORE INTO document_tags (document_id, tag) VALUES (?, ?)",
        [(document_id, tag) for tag in parsed.tags],
    )
    connection.executemany(
        "INSERT OR IGNORE INTO document_aliases (document_id, alias) VALUES (?, ?)",
        [(document_id, alias) for alias in parsed.aliases],
    )
    connection.commit()
    return document_id


def _delete_document_chunks(connection: sqlite3.Connection, document_id: int) -> None:
    chunk_rows = connection.execute("SELECT id FROM chunks WHERE document_id = ?", (document_id,)).fetchall()
    chunk_ids = [int(row["id"]) for row in chunk_rows]
    if chunk_ids:
        connection.executemany("DELETE FROM embeddings WHERE chunk_id = ?", [(chunk_id,) for chunk_id in chunk_ids])
        connection.executemany("DELETE FROM chunks_fts WHERE chunk_id = ?", [(chunk_id,) for chunk_id in chunk_ids])
    connection.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
    connection.commit()


def _insert_chunks(connection: sqlite3.Connection, document_id: int, title: str, chunks: list[ChunkRecord]) -> list[int]:
    chunk_ids: list[int] = []
    now = utc_now_iso()
    for chunk in chunks:
        cursor = connection.execute(
            """
            INSERT INTO chunks (
                document_id, chunk_index, section_title, text, token_estimate,
                char_start, char_end, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                chunk.chunk_index,
                chunk.section_title,
                chunk.text,
                chunk.token_estimate,
                chunk.char_start,
                chunk.char_end,
                now,
            ),
        )
        chunk_id = int(cursor.lastrowid)
        chunk_ids.append(chunk_id)
        connection.execute(
            """
            INSERT INTO chunks_fts (chunk_id, document_title, section_title, text)
            VALUES (?, ?, ?, ?)
            """,
            (chunk_id, title, chunk.section_title or "", chunk.text),
        )
    connection.commit()
    return chunk_ids


def _insert_embeddings(connection: sqlite3.Connection, chunk_ids: list[int], texts: list[str], settings: Settings) -> None:
    vectors = embed_texts(texts, settings.embedding_model_name)
    connection.executemany(
        """
        INSERT INTO embeddings (chunk_id, model_name, vector_json, created_at)
        VALUES (?, ?, ?, ?)
        """,
        [
            (chunk_id, settings.embedding_model_name, json.dumps(vector), utc_now_iso())
            for chunk_id, vector in zip(chunk_ids, vectors)
        ],
    )
    connection.commit()


def _ingest_single_document(connection: sqlite3.Connection, path: Path, settings: Settings) -> tuple[str, int | None]:
    parsed = parse_markdown_file(path)
    content_hash = sha256_text(parsed.raw_text)
    existing = _get_document_row(connection, str(path))
    if existing is not None and existing["content_hash"] == content_hash:
        LOGGER.info("Skipping unchanged file %s", path)
        return "skipped", int(existing["id"])

    last_modified = utc_now_iso()
    document_id = _upsert_document(connection, parsed, content_hash, last_modified)
    _delete_document_chunks(connection, document_id)
    chunks = chunk_document(parsed.normalized_text)
    chunk_ids = _insert_chunks(connection, document_id, parsed.title, chunks)
    if chunk_ids:
        _insert_embeddings(connection, chunk_ids, [chunk.text for chunk in chunks], settings)
    LOGGER.info("Indexed %s with %d chunks", path, len(chunk_ids))
    return "indexed", document_id


def ingest_vault(connection: sqlite3.Connection, vault_path: Path, settings: Settings) -> dict[str, object]:
    run_id = _record_run(connection, "ingest", vault_path, "running")
    counts = {"indexed": 0, "skipped": 0}
    for path in scan_markdown_files(vault_path):
        status, _ = _ingest_single_document(connection, path, settings)
        counts[status] += 1
    _record_run(connection, "ingest", vault_path, "completed", counts["indexed"], run_id=run_id)
    return {
        "run_id": run_id,
        "vault_path": str(vault_path),
        "indexed": counts["indexed"],
        "skipped": counts["skipped"],
    }


def reindex_vault(connection: sqlite3.Connection, vault_path: Path, settings: Settings) -> dict[str, object]:
    run_id = _record_run(connection, "reindex", vault_path, "running")
    connection.execute("DELETE FROM embeddings")
    connection.execute("DELETE FROM chunks_fts")
    connection.execute("DELETE FROM chunks")
    connection.commit()

    indexed = 0
    for path in scan_markdown_files(vault_path):
        parsed = parse_markdown_file(path)
        content_hash = sha256_text(parsed.raw_text)
        document_id = _upsert_document(connection, parsed, content_hash, utc_now_iso())
        chunks = chunk_document(parsed.normalized_text)
        chunk_ids = _insert_chunks(connection, document_id, parsed.title, chunks)
        if chunk_ids:
            _insert_embeddings(connection, chunk_ids, [chunk.text for chunk in chunks], settings)
        indexed += 1
    _record_run(connection, "reindex", vault_path, "completed", indexed, run_id=run_id)
    return {"run_id": run_id, "vault_path": str(vault_path), "indexed": indexed, "skipped": 0}


def status_summary(connection: sqlite3.Connection) -> dict[str, object]:
    documents = connection.execute("SELECT COUNT(*) AS count FROM documents").fetchone()["count"]
    chunks = connection.execute("SELECT COUNT(*) AS count FROM chunks").fetchone()["count"]
    embeddings = connection.execute("SELECT COUNT(*) AS count FROM embeddings").fetchone()["count"]
    latest_run = connection.execute(
        """
        SELECT id, run_type, status, document_count, created_at, completed_at
        FROM ingestion_runs
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    return {
        "documents": documents,
        "chunks": chunks,
        "embeddings": embeddings,
        "latest_run": dict(latest_run) if latest_run else None,
    }
