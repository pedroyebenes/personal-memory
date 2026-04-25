from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from app.config import Settings
from app.models import ChunkRecord, ParsedDocument
from app.processing.chunker import chunk_document
from app.processing.concepts import ConceptMention, extract_concept_mentions
from app.processing.embeddings import embed_texts
from app.util.hashing import sha256_text
from app.util.logging import get_logger
from app.util.timestamps import utc_now_iso
from app.vault.obsidian_parser import parse_markdown_file
from app.vault.scanner import ScannedFile, scan_markdown_entries

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


def _prune_documents_not_in_vault(
    connection: sqlite3.Connection, current_paths: set[str]
) -> list[int]:
    rows = connection.execute("SELECT id, source_path FROM documents").fetchall()
    stale_ids = [int(row["id"]) for row in rows if row["source_path"] not in current_paths]
    if not stale_ids:
        return []
    connection.executemany("DELETE FROM documents WHERE id = ?", [(document_id,) for document_id in stale_ids])
    connection.commit()
    LOGGER.info("Pruned %d stale documents from the index", len(stale_ids))
    return stale_ids


def _upsert_document(
    connection: sqlite3.Connection,
    parsed: ParsedDocument,
    content_hash: str,
    last_modified: str,
    file_size: int,
) -> int:
    now = utc_now_iso()
    existing = _get_document_row(connection, str(parsed.source_path))
    if existing is None:
        cursor = connection.execute(
            """
            INSERT INTO documents (
                source_path, title, raw_text, normalized_text, frontmatter_json,
                content_hash, last_modified, file_size, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(parsed.source_path),
                parsed.title,
                parsed.raw_text,
                parsed.normalized_text,
                json.dumps(parsed.frontmatter, sort_keys=True),
                content_hash,
                last_modified,
                file_size,
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
                content_hash = ?, last_modified = ?, file_size = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                parsed.title,
                parsed.raw_text,
                parsed.normalized_text,
                json.dumps(parsed.frontmatter, sort_keys=True),
                content_hash,
                last_modified,
                file_size,
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


def _upsert_entity(connection: sqlite3.Connection, mention: ConceptMention) -> int:
    now = utc_now_iso()
    row = connection.execute(
        "SELECT id, canonical_name, entity_type FROM entities WHERE normalized_key = ?",
        (mention.normalized_key,),
    ).fetchone()
    if row is None:
        cursor = connection.execute(
            """
            INSERT INTO entities (canonical_name, normalized_key, entity_type, metadata_json, mention_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, 0, ?, ?)
            """,
            (mention.canonical_name, mention.normalized_key, mention.entity_type, "{}", now, now),
        )
        return int(cursor.lastrowid)
    entity_id = int(row["id"])
    if not row["canonical_name"] and mention.canonical_name:
        connection.execute(
            "UPDATE entities SET canonical_name = ?, updated_at = ? WHERE id = ?",
            (mention.canonical_name, now, entity_id),
        )
    if row["entity_type"] != "concept" and mention.entity_type == "concept":
        connection.execute(
            "UPDATE entities SET entity_type = ?, updated_at = ? WHERE id = ?",
            ("concept", now, entity_id),
        )
    return entity_id


def _insert_concept_mentions(
    connection: sqlite3.Connection,
    chunk_ids: list[int],
    mentions: list[ConceptMention],
) -> int:
    if not mentions or not chunk_ids:
        return 0
    now = utc_now_iso()
    inserted = 0
    for mention in mentions:
        if mention.chunk_index < 0 or mention.chunk_index >= len(chunk_ids):
            continue
        chunk_id = chunk_ids[mention.chunk_index]
        entity_id = _upsert_entity(connection, mention)
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO entity_mentions
                (entity_id, chunk_id, mention_text, extraction_method, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (entity_id, chunk_id, mention.mention_text, mention.extraction_method, now),
        )
        if cursor.rowcount:
            inserted += 1
    return inserted


def _refresh_entity_mention_counts(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        UPDATE entities
        SET mention_count = COALESCE(
            (SELECT COUNT(*) FROM entity_mentions WHERE entity_id = entities.id),
            0
        )
        """
    )


def _prune_orphan_entities(connection: sqlite3.Connection) -> int:
    cursor = connection.execute("DELETE FROM entities WHERE mention_count = 0")
    return cursor.rowcount or 0


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


def _ingest_single_document(
    connection: sqlite3.Connection,
    entry: ScannedFile,
    settings: Settings,
) -> tuple[str, int | None, list[str]]:
    path = entry.path
    existing = _get_document_row(connection, str(path))
    if (
        existing is not None
        and existing["last_modified"] == entry.mtime_iso
        and int(existing["file_size"] or 0) == entry.size
    ):
        LOGGER.info("Skipping unchanged file (mtime+size match) %s", path)
        return "skipped", int(existing["id"]), []

    parsed, warnings = parse_markdown_file(path)
    content_hash = sha256_text(parsed.raw_text)
    if existing is not None and existing["content_hash"] == content_hash:
        # File touched but content unchanged: refresh stat-side bookkeeping only.
        connection.execute(
            "UPDATE documents SET last_modified = ?, file_size = ?, updated_at = ? WHERE id = ?",
            (entry.mtime_iso, entry.size, utc_now_iso(), int(existing["id"])),
        )
        connection.commit()
        LOGGER.info("Skipping unchanged content for %s", path)
        return "skipped", int(existing["id"]), warnings

    document_id = _upsert_document(connection, parsed, content_hash, entry.mtime_iso, entry.size)
    _delete_document_chunks(connection, document_id)
    chunks = chunk_document(parsed.normalized_text)
    chunk_ids = _insert_chunks(connection, document_id, parsed.title, chunks)
    if chunk_ids:
        _insert_embeddings(connection, chunk_ids, [chunk.text for chunk in chunks], settings)
        mentions = extract_concept_mentions(parsed, chunks)
        _insert_concept_mentions(connection, chunk_ids, mentions)
    LOGGER.info("Indexed %s with %d chunks", path, len(chunk_ids))
    return "indexed", document_id, warnings


def _resolve_scope(settings: Settings) -> tuple[Iterable[str], Iterable[str]]:
    return settings.ingest_include, settings.ingest_exclude


def _build_failure(path: Path, exc: BaseException) -> dict[str, object]:
    return {
        "path": str(path),
        "error_type": exc.__class__.__name__,
        "error": str(exc),
    }


def ingest_vault(connection: sqlite3.Connection, vault_path: Path, settings: Settings) -> dict[str, object]:
    run_id = _record_run(connection, "ingest", vault_path, "running")
    counts = {"indexed": 0, "skipped": 0}
    failures: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []
    changed_document_ids: list[int] = []
    removed_document_ids: list[int] = []
    include, exclude = _resolve_scope(settings)
    try:
        entries = scan_markdown_entries(vault_path, include=include, exclude=exclude)
        current_paths = {str(entry.path) for entry in entries}
        removed_document_ids = _prune_documents_not_in_vault(connection, current_paths)
        for entry in entries:
            try:
                status, document_id, file_warnings = _ingest_single_document(connection, entry, settings)
            except Exception as exc:  # noqa: BLE001 — capture per-file failures, keep ingest going
                LOGGER.warning("Failed to ingest %s: %s", entry.path, exc)
                failures.append(_build_failure(entry.path, exc))
                continue
            counts[status] += 1
            if status == "indexed" and document_id is not None:
                changed_document_ids.append(document_id)
            if file_warnings and document_id is not None:
                warnings.append({"path": str(entry.path), "warnings": file_warnings})
    except Exception:
        _record_run(connection, "ingest", vault_path, "failed", counts["indexed"], run_id=run_id)
        raise
    _refresh_entity_mention_counts(connection)
    pruned_entities = _prune_orphan_entities(connection)
    connection.commit()
    final_status = "completed" if not failures else "completed_with_errors"
    _record_run(connection, "ingest", vault_path, final_status, counts["indexed"], run_id=run_id)
    return {
        "run_id": run_id,
        "status": final_status,
        "vault_path": str(vault_path),
        "indexed": counts["indexed"],
        "skipped": counts["skipped"],
        "pruned": len(removed_document_ids),
        "failed": len(failures),
        "failures": failures,
        "warnings": warnings,
        "changed_document_ids": changed_document_ids,
        "removed_document_ids": removed_document_ids,
        "pruned_entities": pruned_entities,
        "scope": {"include": list(include), "exclude": list(exclude)},
    }


def reindex_vault(connection: sqlite3.Connection, vault_path: Path, settings: Settings) -> dict[str, object]:
    run_id = _record_run(connection, "reindex", vault_path, "running")
    connection.execute("DELETE FROM entity_mentions")
    connection.execute("DELETE FROM entities")
    connection.execute("DELETE FROM embeddings")
    connection.execute("DELETE FROM chunks_fts")
    connection.execute("DELETE FROM chunks")
    connection.execute("DELETE FROM document_tags")
    connection.execute("DELETE FROM document_aliases")
    connection.execute("DELETE FROM documents")
    connection.commit()

    indexed = 0
    failures: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []
    changed_document_ids: list[int] = []
    include, exclude = _resolve_scope(settings)
    try:
        entries = scan_markdown_entries(vault_path, include=include, exclude=exclude)
        for entry in entries:
            try:
                parsed, file_warnings = parse_markdown_file(entry.path)
                content_hash = sha256_text(parsed.raw_text)
                document_id = _upsert_document(connection, parsed, content_hash, entry.mtime_iso, entry.size)
                chunks = chunk_document(parsed.normalized_text)
                chunk_ids = _insert_chunks(connection, document_id, parsed.title, chunks)
                if chunk_ids:
                    _insert_embeddings(connection, chunk_ids, [chunk.text for chunk in chunks], settings)
                    mentions = extract_concept_mentions(parsed, chunks)
                    _insert_concept_mentions(connection, chunk_ids, mentions)
                indexed += 1
                changed_document_ids.append(document_id)
                if file_warnings:
                    warnings.append({"path": str(entry.path), "warnings": file_warnings})
            except Exception as exc:  # noqa: BLE001 — isolate per-file failures
                LOGGER.warning("Failed to reindex %s: %s", entry.path, exc)
                failures.append(_build_failure(entry.path, exc))
    except Exception:
        _record_run(connection, "reindex", vault_path, "failed", indexed, run_id=run_id)
        raise
    _refresh_entity_mention_counts(connection)
    pruned_entities = _prune_orphan_entities(connection)
    connection.commit()
    final_status = "completed" if not failures else "completed_with_errors"
    _record_run(connection, "reindex", vault_path, final_status, indexed, run_id=run_id)
    return {
        "run_id": run_id,
        "status": final_status,
        "vault_path": str(vault_path),
        "indexed": indexed,
        "skipped": 0,
        "pruned": 0,
        "failed": len(failures),
        "failures": failures,
        "warnings": warnings,
        "changed_document_ids": changed_document_ids,
        "removed_document_ids": [],
        "pruned_entities": pruned_entities,
        "scope": {"include": list(include), "exclude": list(exclude)},
    }


def refresh_concepts(connection: sqlite3.Connection) -> dict[str, object]:
    """Rebuild the concept layer from existing chunks without touching documents/embeddings."""
    connection.execute("DELETE FROM entity_mentions")
    connection.execute("DELETE FROM entities")
    connection.commit()
    rows = connection.execute(
        """
        SELECT
            d.id AS document_id,
            d.source_path,
            d.title,
            d.frontmatter_json
        FROM documents d
        ORDER BY d.id
        """
    ).fetchall()

    indexed_documents = 0
    total_mentions = 0
    for row in rows:
        document_id = int(row["document_id"])
        chunk_rows = connection.execute(
            """
            SELECT id, chunk_index, section_title, text
            FROM chunks WHERE document_id = ? ORDER BY chunk_index
            """,
            (document_id,),
        ).fetchall()
        if not chunk_rows:
            continue

        chunk_records: list[ChunkRecord] = [
            ChunkRecord(
                chunk_index=int(c["chunk_index"]),
                section_title=c["section_title"],
                text=c["text"],
                token_estimate=0,
                char_start=0,
                char_end=0,
            )
            for c in chunk_rows
        ]
        chunk_ids = [int(c["id"]) for c in chunk_rows]

        try:
            frontmatter = json.loads(row["frontmatter_json"] or "{}")
        except json.JSONDecodeError:
            frontmatter = {}
        tags_raw = frontmatter.get("tags") or []
        aliases_raw = frontmatter.get("aliases") or []
        tags = [str(item).strip() for item in (tags_raw if isinstance(tags_raw, list) else [tags_raw]) if str(item).strip()]
        aliases = [str(item).strip() for item in (aliases_raw if isinstance(aliases_raw, list) else [aliases_raw]) if str(item).strip()]

        parsed = ParsedDocument(
            source_path=Path(row["source_path"]),
            title=row["title"],
            raw_text="",
            normalized_text="",
            frontmatter=frontmatter,
            tags=tags,
            aliases=aliases,
        )
        mentions = extract_concept_mentions(parsed, chunk_records)
        total_mentions += _insert_concept_mentions(connection, chunk_ids, mentions)
        indexed_documents += 1

    _refresh_entity_mention_counts(connection)
    pruned_entities = _prune_orphan_entities(connection)
    connection.commit()

    entity_count = int(
        connection.execute("SELECT COUNT(*) AS count FROM entities").fetchone()["count"]
    )
    concept_count = int(
        connection.execute("SELECT COUNT(*) AS count FROM entities WHERE entity_type = 'concept'").fetchone()["count"]
    )
    structure_count = int(
        connection.execute("SELECT COUNT(*) AS count FROM entities WHERE entity_type = 'structure'").fetchone()["count"]
    )
    return {
        "documents": indexed_documents,
        "mentions": total_mentions,
        "entities": entity_count,
        "concepts": concept_count,
        "structures": structure_count,
        "pruned_entities": pruned_entities,
    }


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
