from __future__ import annotations

import sqlite3
from pathlib import Path

from app.db import connect, init_db, table_exists


def test_init_db_adds_heading_path_json_to_legacy_database(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.sqlite3"
    raw = sqlite3.connect(db_path)
    raw.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_path TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            raw_text TEXT NOT NULL,
            normalized_text TEXT NOT NULL,
            frontmatter_json TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            last_modified TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            chunk_index INTEGER NOT NULL,
            section_title TEXT,
            text TEXT NOT NULL,
            token_estimate INTEGER NOT NULL,
            char_start INTEGER NOT NULL,
            char_end INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(document_id, chunk_index),
            FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        """
    )
    raw.close()

    conn = connect(db_path)
    try:
        init_db(conn)
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(chunks)").fetchall()}
        assert "heading_path_json" in cols
        assert table_exists(conn, "schema_meta")
        assert table_exists(conn, "entity_embeddings")
    finally:
        conn.close()


def test_schema_meta_records_core_version(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite3"
    conn = connect(db_path)
    try:
        init_db(conn)
        row = conn.execute("SELECT value FROM schema_meta WHERE key = ?", ("schema_core_version",)).fetchone()
        assert row is not None
        assert int(row["value"]) >= 5
    finally:
        conn.close()
