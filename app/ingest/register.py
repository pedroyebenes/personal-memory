from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from app.config import Settings
from app.db import ensure_chunk_vectors_table, sqlite_vec_available, table_exists
from app.models import ChunkRecord, ParsedDocument
from app.processing.chunker import breadcrumb_text, chunk_document
from app.processing.concepts import (
    ConceptMention,
    entity_type_from_recorded_methods,
    extract_concept_mentions,
    fold_plural_key,
    is_acronym_source,
    normalize_key,
)
from app.processing.embeddings import embed_texts
from app.processing.entity_embedding_sync import sync_entity_embeddings
from app.util.hashing import sha256_text
from app.util.logging import get_logger
from app.util.timestamps import utc_now_iso
from app.vault.obsidian_parser import parse_markdown_file
from app.vault.scanner import ScannedFile, scan_markdown_entries

LOGGER = get_logger(__name__)


def _chunk_vectors_ready(connection: sqlite3.Connection) -> bool:
    return sqlite_vec_available(connection) and table_exists(connection, "chunk_vectors")


def _purge_chunk_vectors_for_chunk_ids(connection: sqlite3.Connection, chunk_ids: list[int]) -> None:
    if not chunk_ids or not _chunk_vectors_ready(connection):
        return
    connection.executemany("DELETE FROM chunk_vectors WHERE chunk_id = ?", [(cid,) for cid in chunk_ids])


def _serialize_vec_embedding(vector: list[float]) -> bytes:
    from sqlite_vec import serialize_float32

    return serialize_float32(vector)


def _upsert_chunk_vector(connection: sqlite3.Connection, chunk_id: int, vector: list[float]) -> None:
    if not _chunk_vectors_ready(connection):
        return
    connection.execute("DELETE FROM chunk_vectors WHERE chunk_id = ?", (chunk_id,))
    blob = _serialize_vec_embedding(vector)
    connection.execute(
        "INSERT INTO chunk_vectors (chunk_id, embedding) VALUES (?, ?)",
        (chunk_id, blob),
    )


def _embedding_texts_for_chunks(parsed: ParsedDocument, chunks: list[ChunkRecord], settings: Settings) -> list[str]:
    if settings.use_breadcrumb_embeddings:
        return [breadcrumb_text(parsed.title, ch.heading_path, ch.text) for ch in chunks]
    return [ch.text for ch in chunks]


def _entity_ids_for_document_chunks(connection: sqlite3.Connection, document_id: int) -> set[int]:
    rows = connection.execute(
        """
        SELECT DISTINCT em.entity_id
        FROM entity_mentions em
        JOIN chunks c ON c.id = em.chunk_id
        WHERE c.document_id = ?
        """,
        (document_id,),
    ).fetchall()
    return {int(r["entity_id"]) for r in rows}


def _rebind_entity_counts_for_entities(connection: sqlite3.Connection, entity_ids: set[int]) -> None:
    if not entity_ids:
        return
    placeholders = ",".join("?" for _ in entity_ids)
    connection.execute(
        f"""
        UPDATE entities
        SET mention_count = COALESCE(
            (SELECT COUNT(*) FROM entity_mentions em WHERE em.entity_id = entities.id),
            0
        )
        WHERE id IN ({placeholders})
        """,
        tuple(entity_ids),
    )


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
    for document_id in stale_ids:
        chunk_rows = connection.execute("SELECT id FROM chunks WHERE document_id = ?", (document_id,)).fetchall()
        _purge_chunk_vectors_for_chunk_ids(connection, [int(r["id"]) for r in chunk_rows])
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
        _purge_chunk_vectors_for_chunk_ids(connection, chunk_ids)
    connection.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
    connection.commit()


def _insert_chunks(connection: sqlite3.Connection, document_id: int, title: str, chunks: list[ChunkRecord]) -> list[int]:
    chunk_ids: list[int] = []
    now = utc_now_iso()
    for chunk in chunks:
        cursor = connection.execute(
            """
            INSERT INTO chunks (
                document_id, chunk_index, section_title, text, heading_path_json,
                token_estimate, char_start, char_end, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                chunk.chunk_index,
                chunk.section_title,
                chunk.text,
                json.dumps(chunk.heading_path, ensure_ascii=False),
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


def _existing_entity_normalized_keys(connection: sqlite3.Connection) -> frozenset[str]:
    rows = connection.execute(
        "SELECT normalized_key FROM entities WHERE normalized_key IS NOT NULL AND normalized_key != ''"
    ).fetchall()
    return frozenset(str(r["normalized_key"]) for r in rows)


def _richer_canonical(existing: str, new: str) -> str:
    if not existing:
        return new
    if not new:
        return existing
    score_existing = (len(existing), sum(1 for c in existing if c.isupper()))
    score_new = (len(new), sum(1 for c in new if c.isupper()))
    return existing if score_existing >= score_new else new


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
    merged = _richer_canonical(str(row["canonical_name"] or ""), mention.canonical_name)
    if merged != row["canonical_name"]:
        connection.execute(
            "UPDATE entities SET canonical_name = ?, updated_at = ? WHERE id = ?",
            (merged, now, entity_id),
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
    if vectors:
        ensure_chunk_vectors_table(connection, len(vectors[0]))
    now = utc_now_iso()
    connection.executemany(
        """
        INSERT INTO embeddings (chunk_id, model_name, vector_json, created_at)
        VALUES (?, ?, ?, ?)
        """,
        [(chunk_id, settings.embedding_model_name, json.dumps(vector), now) for chunk_id, vector in zip(chunk_ids, vectors)],
    )
    if _chunk_vectors_ready(connection):
        for chunk_id, vector in zip(chunk_ids, vectors):
            _upsert_chunk_vector(connection, chunk_id, vector)
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
    touched_entities = _entity_ids_for_document_chunks(connection, document_id)
    _delete_document_chunks(connection, document_id)
    chunks = chunk_document(parsed.normalized_text)
    chunk_ids = _insert_chunks(connection, document_id, parsed.title, chunks)
    if chunk_ids:
        _insert_embeddings(
            connection,
            chunk_ids,
            _embedding_texts_for_chunks(parsed, chunks, settings),
            settings,
        )
        mentions = extract_concept_mentions(
            parsed, chunks, existing_normalized_keys=_existing_entity_normalized_keys(connection)
        )
        _insert_concept_mentions(connection, chunk_ids, mentions)
    touched_entities |= _entity_ids_for_document_chunks(connection, document_id)
    _rebind_entity_counts_for_entities(connection, touched_entities)
    pruned_local = _prune_orphan_entities(connection)
    connection.commit()
    if pruned_local:
        LOGGER.info("Pruned %d orphan entities after indexing %s", pruned_local, path)
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
    entity_embed_stats = sync_entity_embeddings(connection, settings)
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
        "entity_embeddings": entity_embed_stats,
        "scope": {"include": list(include), "exclude": list(exclude)},
    }


def reindex_vault(connection: sqlite3.Connection, vault_path: Path, settings: Settings) -> dict[str, object]:
    run_id = _record_run(connection, "reindex", vault_path, "running")
    if table_exists(connection, "chunk_vectors"):
        connection.execute("DELETE FROM chunk_vectors")
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
                    _insert_embeddings(
                        connection,
                        chunk_ids,
                        _embedding_texts_for_chunks(parsed, chunks, settings),
                        settings,
                    )
                    mentions = extract_concept_mentions(parsed, chunks, existing_normalized_keys=frozenset())
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
    entity_embed_stats = sync_entity_embeddings(connection, settings)
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
        "entity_embeddings": entity_embed_stats,
        "scope": {"include": list(include), "exclude": list(exclude)},
    }


def _merge_and_rekey_entities(connection: sqlite3.Connection) -> dict[str, int]:
    """Collapse entities that share the same post-normalization key; reattach mentions."""
    rows = list(
        connection.execute(
            "SELECT id, canonical_name, normalized_key, entity_type FROM entities ORDER BY id"
        ).fetchall()
    )
    if not rows:
        return {"entities_merged": 0, "entities_rekeyed": 0}
    cores = [normalize_key(str(r["canonical_name"] or "")) for r in rows]
    pool = set(cores)
    groups: dict[str, list[tuple[int, str, str | None]]] = {}
    for r, core in zip(rows, cores):
        canon = str(r["canonical_name"] or "")
        final = fold_plural_key(
            core,
            pool,
            source_is_acronym=is_acronym_source(canon),
        )
        groups.setdefault(final, []).append((int(r["id"]), canon, r["entity_type"]))
    now = utc_now_iso()
    merged = 0
    rekeyed = 0
    for final_key, members in groups.items():
        members.sort(key=lambda t: t[0])
        if len(members) == 1:
            eid = members[0][0]
            current = connection.execute(
                "SELECT normalized_key FROM entities WHERE id = ?", (eid,)
            ).fetchone()
            if current and str(current["normalized_key"]) != final_key:
                connection.execute(
                    "UPDATE entities SET normalized_key = ?, updated_at = ? WHERE id = ?",
                    (final_key, now, eid),
                )
                rekeyed += 1
            continue
        survivor_id = members[0][0]
        survivor_canon = members[0][1]
        for _, canon, _ in members[1:]:
            survivor_canon = _richer_canonical(survivor_canon, canon)
        ets = [et for _, _, et in members]
        survivor_type = "concept" if any(et is None or et == "concept" for et in ets) else "structure"
        for loser_id, _, _ in members[1:]:
            connection.execute(
                "UPDATE entity_mentions SET entity_id = ? WHERE entity_id = ?",
                (survivor_id, loser_id),
            )
            connection.execute("DELETE FROM entities WHERE id = ?", (loser_id,))
            merged += 1
        connection.execute(
            """
            UPDATE entities
            SET canonical_name = ?, normalized_key = ?, entity_type = ?, updated_at = ?
            WHERE id = ?
            """,
            (survivor_canon, final_key, survivor_type, now, survivor_id),
        )
    return {"entities_merged": merged, "entities_rekeyed": rekeyed}


def rebuild_embeddings(
    connection: sqlite3.Connection,
    settings: Settings,
    *,
    use_breadcrumbs: bool | None = None,
) -> dict[str, object]:
    """Re-encode stored chunks and refresh ``embeddings`` (and ``chunk_vectors`` when enabled)."""
    use_bc = settings.use_breadcrumb_embeddings if use_breadcrumbs is None else use_breadcrumbs
    rows = connection.execute(
        """
        SELECT c.id AS chunk_id, d.title AS document_title, c.text, c.heading_path_json
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        ORDER BY c.id
        """
    ).fetchall()
    if not rows:
        return {"status": "ok", "chunks_updated": 0, "use_breadcrumb_embeddings": use_bc}
    batch_size = 48
    updated = 0
    now = utc_now_iso()
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        texts: list[str] = []
        chunk_ids: list[int] = []
        for row in batch:
            raw_path = row["heading_path_json"]
            try:
                path = json.loads(raw_path or "[]")
            except json.JSONDecodeError:
                path = []
            if not isinstance(path, list):
                path = []
            heading_path = [str(x) for x in path]
            body = str(row["text"] or "")
            title = str(row["document_title"] or "")
            texts.append(breadcrumb_text(title, heading_path, body) if use_bc else body)
            chunk_ids.append(int(row["chunk_id"]))
        vectors = embed_texts(texts, settings.embedding_model_name)
        if vectors:
            ensure_chunk_vectors_table(connection, len(vectors[0]))
        for cid, vec in zip(chunk_ids, vectors):
            connection.execute(
                """
                UPDATE embeddings
                SET vector_json = ?, model_name = ?, created_at = ?
                WHERE chunk_id = ?
                """,
                (json.dumps(vec), settings.embedding_model_name, now, cid),
            )
            if _chunk_vectors_ready(connection):
                _upsert_chunk_vector(connection, cid, vec)
        connection.commit()
        updated += len(chunk_ids)
    return {"status": "ok", "chunks_updated": updated, "use_breadcrumb_embeddings": use_bc}


def rebuild_chunk_vectors(connection: sqlite3.Connection) -> dict[str, object]:
    """Populate ``chunk_vectors`` from existing ``embeddings`` without re-encoding."""
    if not sqlite_vec_available(connection):
        return {"status": "skipped", "reason": "sqlite-vec unavailable"}
    rows = connection.execute("SELECT chunk_id, vector_json FROM embeddings ORDER BY chunk_id").fetchall()
    if not rows:
        return {"status": "ok", "rows": 0}
    first = json.loads(rows[0]["vector_json"])
    if not isinstance(first, list) or not first:
        return {"status": "skipped", "reason": "invalid embeddings"}
    ensure_chunk_vectors_table(connection, len(first))
    if not table_exists(connection, "chunk_vectors"):
        return {"status": "skipped", "reason": "chunk_vectors table missing"}
    for row in rows:
        vec_raw = json.loads(row["vector_json"])
        if not isinstance(vec_raw, list):
            continue
        vec = [float(x) for x in vec_raw]
        _upsert_chunk_vector(connection, int(row["chunk_id"]), vec)
    connection.commit()
    return {"status": "ok", "rows": len(rows)}


def reclassify_entities(
    connection: sqlite3.Connection,
    settings: Settings | None = None,
) -> dict[str, object]:
    """Recompute ``entity_type``, re-key rows, and merge duplicates after normalization."""
    rows = connection.execute(
        """
        SELECT e.id, e.canonical_name, e.entity_type,
               GROUP_CONCAT(DISTINCT em.extraction_method) AS methods
        FROM entities e
        LEFT JOIN entity_mentions em ON em.entity_id = e.id
        GROUP BY e.id
        """
    ).fetchall()
    now = utc_now_iso()
    updated = 0
    for row in rows:
        raw_methods = row["methods"]
        methods = {m for m in (raw_methods.split(",") if raw_methods else []) if m}
        canonical = str(row["canonical_name"] or "")
        new_type = entity_type_from_recorded_methods(canonical, methods)
        old_type = row["entity_type"] or "concept"
        if new_type != old_type:
            connection.execute(
                "UPDATE entities SET entity_type = ?, updated_at = ? WHERE id = ?",
                (new_type, now, int(row["id"])),
            )
            updated += 1
    merge_stats = _merge_and_rekey_entities(connection)
    _refresh_entity_mention_counts(connection)
    _prune_orphan_entities(connection)
    connection.commit()
    mention_count = int(connection.execute("SELECT COUNT(*) AS c FROM entity_mentions").fetchone()["c"])
    entity_count = int(connection.execute("SELECT COUNT(*) AS c FROM entities").fetchone()["c"])
    result: dict[str, object] = {
        "entities_scanned": len(rows),
        "entities_updated": updated,
        "entity_mentions": mention_count,
        "entities": entity_count,
        **merge_stats,
    }
    if settings is not None:
        result["entity_embeddings"] = sync_entity_embeddings(connection, settings)
    return result


def refresh_concepts(
    connection: sqlite3.Connection,
    settings: Settings | None = None,
) -> dict[str, object]:
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
    known_keys: set[str] = set()
    for row in rows:
        document_id = int(row["document_id"])
        chunk_rows = connection.execute(
            """
            SELECT id, chunk_index, section_title, text, heading_path_json
            FROM chunks WHERE document_id = ? ORDER BY chunk_index
            """,
            (document_id,),
        ).fetchall()
        if not chunk_rows:
            continue

        chunk_records: list[ChunkRecord] = []
        for c in chunk_rows:
            raw_path = c["heading_path_json"]
            try:
                path = json.loads(raw_path or "[]")
            except json.JSONDecodeError:
                path = []
            if not isinstance(path, list):
                path = []
            chunk_records.append(
                ChunkRecord(
                    chunk_index=int(c["chunk_index"]),
                    section_title=c["section_title"],
                    text=c["text"],
                    token_estimate=0,
                    char_start=0,
                    char_end=0,
                    heading_path=[str(x) for x in path],
                )
            )
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
        mentions = extract_concept_mentions(
            parsed, chunk_records, existing_normalized_keys=frozenset(known_keys)
        )
        total_mentions += _insert_concept_mentions(connection, chunk_ids, mentions)
        known_keys.update(m.normalized_key for m in mentions)
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
    result: dict[str, object] = {
        "documents": indexed_documents,
        "mentions": total_mentions,
        "entities": entity_count,
        "concepts": concept_count,
        "structures": structure_count,
        "pruned_entities": pruned_entities,
    }
    if settings is not None:
        result["entity_embeddings"] = sync_entity_embeddings(connection, settings)
    return result


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
