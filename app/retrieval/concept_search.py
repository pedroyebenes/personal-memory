from __future__ import annotations

import sqlite3

from app.processing.concepts import normalize_key


def _row_to_concept(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": int(row["id"]),
        "canonical_name": row["canonical_name"],
        "normalized_key": row["normalized_key"],
        "entity_type": row["entity_type"],
        "mention_count": int(row["mention_count"] or 0),
    }


def _candidate_keys(terms: list[str]) -> set[str]:
    normalized_terms = [normalize_key(term) for term in terms if normalize_key(term)]
    keys: set[str] = set()
    for start in range(len(normalized_terms)):
        parts: list[str] = []
        for term in normalized_terms[start:]:
            parts.append(term)
            keys.add(normalize_key(" ".join(parts)))
    return keys


def list_concepts(
    connection: sqlite3.Connection,
    *,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, object]]:
    where = ""
    params: list[object] = []
    if search:
        where = "WHERE e.normalized_key LIKE ? OR e.canonical_name LIKE ?"
        token = f"%{normalize_key(search)}%"
        params.extend([token, f"%{search}%"])
    params.extend([int(limit), int(offset)])
    rows = connection.execute(
        f"""
        SELECT
            e.id,
            e.canonical_name,
            e.normalized_key,
            e.entity_type,
            e.mention_count,
            COUNT(DISTINCT c.document_id) AS document_count,
            GROUP_CONCAT(DISTINCT em.extraction_method) AS methods
        FROM entities e
        LEFT JOIN entity_mentions em ON em.entity_id = e.id
        LEFT JOIN chunks c ON c.id = em.chunk_id
        {where}
        GROUP BY e.id
        ORDER BY e.mention_count DESC, e.canonical_name ASC
        LIMIT ? OFFSET ?
        """,
        tuple(params),
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "canonical_name": row["canonical_name"],
            "normalized_key": row["normalized_key"],
            "entity_type": row["entity_type"],
            "mention_count": int(row["mention_count"] or 0),
            "document_count": int(row["document_count"] or 0),
            "extraction_methods": sorted(
                {method for method in (row["methods"] or "").split(",") if method}
            ),
        }
        for row in rows
    ]


def find_concept(
    connection: sqlite3.Connection,
    *,
    concept_id: int | None = None,
    name: str | None = None,
) -> dict[str, object] | None:
    if concept_id is None and not name:
        return None
    if concept_id is not None:
        row = connection.execute(
            "SELECT id, canonical_name, normalized_key, entity_type, mention_count FROM entities WHERE id = ?",
            (concept_id,),
        ).fetchone()
    else:
        key = normalize_key(name or "")
        row = connection.execute(
            "SELECT id, canonical_name, normalized_key, entity_type, mention_count FROM entities WHERE normalized_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            rows = connection.execute(
                """
                SELECT DISTINCT e.id, e.canonical_name, e.normalized_key, e.entity_type, e.mention_count, em.mention_text
                FROM entities e
                JOIN entity_mentions em ON em.entity_id = e.id
                WHERE em.extraction_method = 'alias'
                """,
            ).fetchall()
            row = next((item for item in rows if normalize_key(item["mention_text"]) == key), None)
    if row is None:
        return None
    return _row_to_concept(row)


def get_concept_detail(connection: sqlite3.Connection, concept_id: int) -> dict[str, object] | None:
    concept = find_concept(connection, concept_id=concept_id)
    if concept is None:
        return None
    mention_rows = connection.execute(
        """
        SELECT
            em.id AS mention_id,
            em.mention_text,
            em.extraction_method,
            em.created_at,
            c.id AS chunk_id,
            c.chunk_index,
            c.section_title,
            c.text AS chunk_text,
            d.id AS document_id,
            d.source_path,
            d.title AS document_title
        FROM entity_mentions em
        JOIN chunks c ON c.id = em.chunk_id
        JOIN documents d ON d.id = c.document_id
        WHERE em.entity_id = ?
        ORDER BY d.title, c.chunk_index, em.id
        """,
        (concept_id,),
    ).fetchall()
    mentions = [
        {
            "mention_id": int(row["mention_id"]),
            "mention_text": row["mention_text"],
            "extraction_method": row["extraction_method"],
            "chunk_id": int(row["chunk_id"]),
            "chunk_index": int(row["chunk_index"]),
            "section_title": row["section_title"],
            "chunk_snippet": (row["chunk_text"] or "")[:280],
            "document_id": int(row["document_id"]),
            "document_title": row["document_title"],
            "source_path": row["source_path"],
        }
        for row in mention_rows
    ]
    documents: dict[int, dict[str, object]] = {}
    for mention in mentions:
        document_id = int(mention["document_id"])
        bucket = documents.setdefault(
            document_id,
            {
                "document_id": document_id,
                "document_title": mention["document_title"],
                "source_path": mention["source_path"],
                "mention_count": 0,
                "extraction_methods": set(),
            },
        )
        bucket["mention_count"] = int(bucket["mention_count"]) + 1
        bucket["extraction_methods"].add(mention["extraction_method"])

    document_summary = [
        {
            "document_id": item["document_id"],
            "document_title": item["document_title"],
            "source_path": item["source_path"],
            "mention_count": int(item["mention_count"]),
            "extraction_methods": sorted(item["extraction_methods"]),
        }
        for item in documents.values()
    ]

    return {
        **concept,
        "mentions": mentions,
        "documents": sorted(document_summary, key=lambda item: -item["mention_count"]),
    }


def find_concepts_for_terms(
    connection: sqlite3.Connection,
    terms: list[str],
) -> list[dict[str, object]]:
    """Return concepts whose normalized key matches any token or whose
    aliases (mention_text) match a token. Used for retrieval boosting."""
    if not terms:
        return []
    keys = _candidate_keys(terms)
    if not keys:
        return []
    placeholders = ",".join("?" for _ in keys)
    rows = connection.execute(
        f"""
        SELECT DISTINCT e.id, e.canonical_name, e.normalized_key, e.entity_type, e.mention_count, em.mention_text
        FROM entities e
        LEFT JOIN entity_mentions em ON em.entity_id = e.id AND em.extraction_method = 'alias'
        WHERE e.normalized_key IN ({placeholders})
           OR lower(replace(replace(em.mention_text, '_', ' '), '-', ' ')) IN ({placeholders})
        """,
        (*keys, *keys),
    ).fetchall()
    matched: dict[int, dict[str, object]] = {}
    for row in rows:
        if row["normalized_key"] in keys or normalize_key(row["mention_text"] or "") in keys:
            matched[int(row["id"])] = _row_to_concept(row)
    return [
        matched[entity_id]
        for entity_id in sorted(
            matched,
            key=lambda item: (-int(matched[item]["mention_count"]), str(matched[item]["canonical_name"])),
        )
    ]


def chunks_with_concepts(
    connection: sqlite3.Connection,
    chunk_ids: set[int],
    entity_ids: set[int],
) -> dict[int, set[int]]:
    if not chunk_ids or not entity_ids:
        return {}
    chunk_placeholders = ",".join("?" for _ in chunk_ids)
    entity_placeholders = ",".join("?" for _ in entity_ids)
    rows = connection.execute(
        f"""
        SELECT chunk_id, entity_id
        FROM entity_mentions
        WHERE chunk_id IN ({chunk_placeholders}) AND entity_id IN ({entity_placeholders})
        """,
        (*chunk_ids, *entity_ids),
    ).fetchall()
    matches: dict[int, set[int]] = {}
    for row in rows:
        matches.setdefault(int(row["chunk_id"]), set()).add(int(row["entity_id"]))
    return matches
