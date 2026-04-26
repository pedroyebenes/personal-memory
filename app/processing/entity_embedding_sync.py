from __future__ import annotations

import json
import sqlite3

from app.config import Settings
from app.processing.embeddings import embed_texts
from app.util.hashing import sha256_text
from app.util.timestamps import utc_now_iso

MENTION_METHOD_RANK = {
    "wikilink": 0,
    "definition": 1,
    "emphasis": 2,
    "tag": 3,
    "alias": 4,
    "inline_tag": 5,
    "title": 6,
    "heading": 7,
    "filename": 8,
    "body_phrase": 9,
    "unknown": 99,
}
MAX_ENTITY_EMBED_CHARS = 500
MENTIONS_TO_USE = 8
CHUNK_SNIP_LEN = 160


def _qualifying_entities_sql(entity_ids: set[int] | None) -> tuple[str, tuple[object, ...]]:
    base = """
        SELECT e.id, e.canonical_name
        FROM entities e
        WHERE (e.entity_type = 'concept' OR e.entity_type IS NULL)
          AND e.mention_count >= 2
    """
    if entity_ids is None:
        return base, ()
    if not entity_ids:
        return base + " AND 1=0", ()
    ph = ",".join("?" for _ in entity_ids)
    return base + f" AND e.id IN ({ph})", tuple(entity_ids)


def _mention_rows(connection: sqlite3.Connection, entity_id: int) -> list[sqlite3.Row]:
    return list(
        connection.execute(
            """
            SELECT em.mention_text, em.extraction_method, c.text AS chunk_text
            FROM entity_mentions em
            JOIN chunks c ON c.id = em.chunk_id
            WHERE em.entity_id = ?
            """,
            (entity_id,),
        ).fetchall()
    )


def _sorted_mentions(rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    def sort_key(r: sqlite3.Row) -> tuple[int, int, int]:
        meth = str(r["extraction_method"] or "unknown")
        rank = MENTION_METHOD_RANK.get(meth, 50)
        mt = str(r["mention_text"] or "")
        ct = str(r["chunk_text"] or "")
        return (rank, -len(mt), -len(ct))

    return sorted(rows, key=sort_key)


def build_entity_embedding_text_and_hash(
    connection: sqlite3.Connection,
    entity_id: int,
    canonical_name: str,
) -> tuple[str, str] | None:
    rows = _mention_rows(connection, entity_id)
    if not rows:
        return None
    fp_parts = [canonical_name]
    snippets: list[str] = []
    for r in _sorted_mentions(rows)[:MENTIONS_TO_USE]:
        meth = str(r["extraction_method"] or "")
        mt = (r["mention_text"] or "").strip()
        ct = (str(r["chunk_text"] or "").strip().replace("\n", " "))[:CHUNK_SNIP_LEN]
        excerpt = mt if len(mt) >= 12 else (mt or ct)
        excerpt = excerpt[:CHUNK_SNIP_LEN]
        if excerpt:
            snippets.append(excerpt)
        fp_parts.append(f"{meth}|{mt}|{ct[:40]}")
    body = (canonical_name + " — " + " · ".join(snippets))[:MAX_ENTITY_EMBED_CHARS]
    return body, sha256_text("\n".join(fp_parts))


def sync_entity_embeddings(
    connection: sqlite3.Connection,
    settings: Settings,
    *,
    entity_ids: set[int] | None = None,
) -> dict[str, int | str]:
    """Refresh ``entity_embeddings`` for concepts with ``mention_count >= 2``."""
    connection.execute(
        """
        DELETE FROM entity_embeddings
        WHERE entity_id NOT IN (
            SELECT id FROM entities
            WHERE (entity_type = 'concept' OR entity_type IS NULL)
              AND mention_count >= 2
        )
        """
    )
    sql, extra = _qualifying_entities_sql(entity_ids)
    candidates = connection.execute(sql, extra).fetchall()
    pending: list[tuple[int, str, str]] = []
    skipped = 0
    for row in candidates:
        eid = int(row["id"])
        canon = str(row["canonical_name"] or "")
        built = build_entity_embedding_text_and_hash(connection, eid, canon)
        if not built:
            skipped += 1
            continue
        text, fp = built
        existing = connection.execute(
            "SELECT content_hash, model_name FROM entity_embeddings WHERE entity_id = ?",
            (eid,),
        ).fetchone()
        if (
            existing
            and str(existing["content_hash"] or "") == fp
            and str(existing["model_name"] or "") == settings.embedding_model_name
        ):
            skipped += 1
            continue
        pending.append((eid, text, fp))

    if not pending:
        connection.commit()
        return {"updated": 0, "skipped": skipped, "candidates": len(candidates)}

    batch_size = 32
    updated = 0
    now = utc_now_iso()
    for i in range(0, len(pending), batch_size):
        batch = pending[i : i + batch_size]
        vectors = embed_texts([t for _, t, _ in batch], settings.embedding_model_name)
        for (eid, _, fp), vec in zip(batch, vectors):
            connection.execute(
                """
                INSERT INTO entity_embeddings (entity_id, model_name, vector_json, content_hash, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(entity_id) DO UPDATE SET
                    model_name = excluded.model_name,
                    vector_json = excluded.vector_json,
                    content_hash = excluded.content_hash,
                    created_at = excluded.created_at
                """,
                (eid, settings.embedding_model_name, json.dumps(vec), fp, now),
            )
            updated += 1
    connection.commit()
    return {"updated": updated, "skipped": skipped, "candidates": len(candidates)}
