from __future__ import annotations

import sqlite3
from pathlib import Path

from app.processing.concepts import normalize_key


def connect(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _existing_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _table_count(connection: sqlite3.Connection, table: str) -> int:
    if not _table_exists(connection, table):
        return 0
    return int(connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])


def _prepare_legacy_concept_tables(connection: sqlite3.Connection) -> None:
    """Move pre-Phase-6 concept tables aside so the canonical schema can be created."""
    entity_columns = _existing_columns(connection, "entities")
    if entity_columns and "normalized_key" not in entity_columns:
        if _table_count(connection, "entities") == 0 and _table_count(connection, "entity_mentions") == 0:
            connection.execute("DROP TABLE IF EXISTS entity_mentions")
            connection.execute("DROP TABLE IF EXISTS entities")
            return
        if not _table_exists(connection, "entities_legacy_phase6"):
            if _table_exists(connection, "entity_mentions"):
                connection.execute("ALTER TABLE entity_mentions RENAME TO entity_mentions_legacy_phase6")
            connection.execute("ALTER TABLE entities RENAME TO entities_legacy_phase6")


def _migrate_legacy_concept_tables(connection: sqlite3.Connection) -> None:
    if not _table_exists(connection, "entities_legacy_phase6"):
        return
    now = "1970-01-01T00:00:00+00:00"
    entity_id_map: dict[int, int] = {}
    rows = connection.execute(
        """
        SELECT id, canonical_name, entity_type, metadata_json, created_at
        FROM entities_legacy_phase6
        ORDER BY id
        """
    ).fetchall()
    for row in rows:
        old_id = int(row["id"])
        canonical_name = str(row["canonical_name"] or "").strip() or f"Entity {old_id}"
        normalized_key = normalize_key(canonical_name) or f"entity {old_id}"
        existing = connection.execute(
            "SELECT id FROM entities WHERE normalized_key = ?",
            (normalized_key,),
        ).fetchone()
        if existing is not None:
            entity_id_map[old_id] = int(existing["id"])
            continue
        cursor = connection.execute(
            """
            INSERT INTO entities (canonical_name, normalized_key, entity_type, metadata_json, mention_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, 0, ?, ?)
            """,
            (
                canonical_name,
                normalized_key,
                row["entity_type"] or "concept",
                row["metadata_json"] or "{}",
                row["created_at"] or now,
                row["created_at"] or now,
            ),
        )
        entity_id_map[old_id] = int(cursor.lastrowid)

    if _table_exists(connection, "entity_mentions_legacy_phase6"):
        mention_rows = connection.execute(
            """
            SELECT entity_id, chunk_id, mention_text, created_at
            FROM entity_mentions_legacy_phase6
            ORDER BY id
            """
        ).fetchall()
        for row in mention_rows:
            new_entity_id = entity_id_map.get(int(row["entity_id"]))
            if new_entity_id is None:
                continue
            connection.execute(
                """
                INSERT OR IGNORE INTO entity_mentions
                    (entity_id, chunk_id, mention_text, extraction_method, created_at)
                VALUES (?, ?, ?, 'unknown', ?)
                """,
                (
                    new_entity_id,
                    int(row["chunk_id"]),
                    str(row["mention_text"] or "").strip() or "unknown",
                    row["created_at"] or now,
                ),
            )

    connection.execute(
        """
        UPDATE entities
        SET mention_count = COALESCE(
            (SELECT COUNT(*) FROM entity_mentions WHERE entity_id = entities.id),
            0
        )
        """
    )
    connection.execute("DROP TABLE IF EXISTS entity_mentions_legacy_phase6")
    connection.execute("DROP TABLE IF EXISTS entities_legacy_phase6")


def _apply_migrations(connection: sqlite3.Connection) -> None:
    document_columns = _existing_columns(connection, "documents")
    if "file_size" not in document_columns:
        connection.execute("ALTER TABLE documents ADD COLUMN file_size INTEGER NOT NULL DEFAULT 0")
    chunk_columns = _existing_columns(connection, "chunks")
    if chunk_columns and "heading_path_json" not in chunk_columns:
        connection.execute("ALTER TABLE chunks ADD COLUMN heading_path_json TEXT NOT NULL DEFAULT '[]'")


def init_db(connection: sqlite3.Connection, schema_path: Path | None = None) -> None:
    resolved_schema = schema_path or Path(__file__).with_name("schema.sql")
    _prepare_legacy_concept_tables(connection)
    connection.executescript(resolved_schema.read_text(encoding="utf-8"))
    _apply_migrations(connection)
    _migrate_legacy_concept_tables(connection)
    connection.commit()
