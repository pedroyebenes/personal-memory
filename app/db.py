from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _existing_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}


def _apply_migrations(connection: sqlite3.Connection) -> None:
    document_columns = _existing_columns(connection, "documents")
    if "file_size" not in document_columns:
        connection.execute("ALTER TABLE documents ADD COLUMN file_size INTEGER NOT NULL DEFAULT 0")


def init_db(connection: sqlite3.Connection, schema_path: Path | None = None) -> None:
    resolved_schema = schema_path or Path(__file__).with_name("schema.sql")
    connection.executescript(resolved_schema.read_text(encoding="utf-8"))
    _apply_migrations(connection)
    connection.commit()
