from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.processing.concepts import normalize_key
from app.util.logging import get_logger

LOGGER = get_logger(__name__)

DEFAULT_VECTOR_DIMENSION = 384


class PMConnection(sqlite3.Connection):
    """``sqlite3`` connection that records whether the optional sqlite-vec extension loaded."""

    sqlite_vec_available: bool = False


def sqlite_vec_available(connection: sqlite3.Connection) -> bool:
    if isinstance(connection, PMConnection):
        return bool(connection.sqlite_vec_available)
    return False


def connect(database_path: Path) -> PMConnection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(database_path), factory=PMConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    vec_ok = False
    try:
        connection.enable_load_extension(True)
    except AttributeError:
        vec_ok = False
    else:
        try:
            import sqlite_vec  # type: ignore[import-not-found]

            sqlite_vec.load(connection)
            vec_ok = True
        except Exception as exc:  # noqa: BLE001 — optional extension
            LOGGER.info("sqlite-vec not loaded (%s); ANN index disabled", exc.__class__.__name__)
            vec_ok = False
    connection.sqlite_vec_available = vec_ok
    return connection


def _existing_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _table_count(connection: sqlite3.Connection, table: str) -> int:
    if not table_exists(connection, table):
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
        if not table_exists(connection, "entities_legacy_phase6"):
            if table_exists(connection, "entity_mentions"):
                connection.execute("ALTER TABLE entity_mentions RENAME TO entity_mentions_legacy_phase6")
            connection.execute("ALTER TABLE entities RENAME TO entities_legacy_phase6")


def _migrate_legacy_concept_tables(connection: sqlite3.Connection) -> None:
    if not table_exists(connection, "entities_legacy_phase6"):
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

    if table_exists(connection, "entity_mentions_legacy_phase6"):
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


def _infer_embedding_dimension(connection: sqlite3.Connection, default: int = DEFAULT_VECTOR_DIMENSION) -> int:
    if not table_exists(connection, "embeddings"):
        return default
    row = connection.execute("SELECT vector_json FROM embeddings LIMIT 1").fetchone()
    if not row or not row["vector_json"]:
        return default
    try:
        vec = json.loads(row["vector_json"])
    except json.JSONDecodeError:
        return default
    return len(vec) if isinstance(vec, list) and vec else default


def _schema_meta_set(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
        (key, value),
    )


def _apply_schema_migrations(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )

    if table_exists(connection, "documents"):
        document_columns = _existing_columns(connection, "documents")
        if document_columns and "file_size" not in document_columns:
            connection.execute("ALTER TABLE documents ADD COLUMN file_size INTEGER NOT NULL DEFAULT 0")
        _schema_meta_set(connection, "migration_documents_file_size", "1")

    chunk_columns = _existing_columns(connection, "chunks") if table_exists(connection, "chunks") else set()
    if chunk_columns and "heading_path_json" not in chunk_columns:
        connection.execute("ALTER TABLE chunks ADD COLUMN heading_path_json TEXT NOT NULL DEFAULT '[]'")
    if table_exists(connection, "chunks"):
        _schema_meta_set(connection, "migration_chunks_heading_path_json", "1")

    if table_exists(connection, "entity_embeddings"):
        _schema_meta_set(connection, "migration_entity_embeddings", "1")

    if table_exists(connection, "chunk_vectors"):
        _schema_meta_set(connection, "migration_chunk_vectors", str(_infer_embedding_dimension(connection)))

    _schema_meta_set(connection, "schema_core_version", "5")


def ensure_chunk_vectors_table(connection: sqlite3.Connection, dimension: int) -> None:
    """Create the sqlite-vec ANN table once, sized to match stored embedding vectors."""
    if not sqlite_vec_available(connection):
        return
    if table_exists(connection, "chunk_vectors"):
        return
    if dimension < 1:
        return
    connection.execute(
        f"CREATE VIRTUAL TABLE chunk_vectors USING vec0(chunk_id INTEGER PRIMARY KEY, embedding float[{dimension}])"
    )
    _schema_meta_set(connection, "migration_chunk_vectors", str(dimension))


def init_db(connection: sqlite3.Connection, schema_path: Path | None = None) -> None:
    resolved_schema = schema_path or Path(__file__).with_name("schema.sql")
    _prepare_legacy_concept_tables(connection)
    connection.executescript(resolved_schema.read_text(encoding="utf-8"))
    _apply_schema_migrations(connection)
    _migrate_legacy_concept_tables(connection)
    connection.commit()
