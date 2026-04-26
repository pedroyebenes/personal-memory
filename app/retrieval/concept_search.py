from __future__ import annotations

import sqlite3

from app.processing.concepts import normalize_key, normalized_key_is_stopword_only
from app.retrieval.sources import build_markdown_ref, build_source_ref

STRONG_CONCEPT_METHODS = {"wikilink", "tag", "alias", "definition", "inline_tag"}
MEDIUM_CONCEPT_METHODS = {"title", "heading", "filename", "emphasis", "body_phrase"}
CONCEPT_QUALITIES = {"strong", "medium", "weak", "all"}


def concept_quality(methods: set[str], mention_count: int = 0) -> str:
    if methods.intersection(STRONG_CONCEPT_METHODS):
        return "strong"
    if methods.intersection(MEDIUM_CONCEPT_METHODS):
        return "medium"
    return "weak" if mention_count <= 1 else "medium"


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
    return {k for k in keys if k and not normalized_key_is_stopword_only(k)}


def list_concepts(
    connection: sqlite3.Connection,
    *,
    search: str | None = None,
    entity_type: str | None = "concept",
    method: str | None = None,
    quality: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, object]]:
    where_parts: list[str] = []
    params: list[object] = []
    if entity_type:
        where_parts.append("e.entity_type = ?")
        params.append(entity_type)
    if search:
        where_parts.append("(e.normalized_key LIKE ? OR e.canonical_name LIKE ?)")
        token = f"%{normalize_key(search)}%"
        params.extend([token, f"%{search}%"])
    if method:
        where_parts.append(
            """
            EXISTS (
                SELECT 1
                FROM entity_mentions em_filter
                WHERE em_filter.entity_id = e.id
                  AND em_filter.extraction_method = ?
            )
            """
        )
        params.append(method)
    where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
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
        """,
        tuple(params),
    ).fetchall()
    items: list[dict[str, object]] = []
    for row in rows:
        methods = sorted({method for method in (row["methods"] or "").split(",") if method})
        mention_count = int(row["mention_count"] or 0)
        item_quality = concept_quality(set(methods), mention_count)
        if quality and quality != "all" and item_quality != quality:
            continue
        items.append(
            {
            "id": int(row["id"]),
            "canonical_name": row["canonical_name"],
            "normalized_key": row["normalized_key"],
            "entity_type": row["entity_type"],
            "mention_count": mention_count,
            "document_count": int(row["document_count"] or 0),
            "extraction_methods": methods,
            "quality": item_quality,
            }
        )
    start = int(offset)
    end = start + int(limit)
    return items[start:end]


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
    chunks: dict[int, dict[str, object]] = {}
    for mention in mentions:
        chunk_id = int(mention["chunk_id"])
        bucket = chunks.setdefault(
            chunk_id,
            {
                "chunk_id": chunk_id,
                "chunk_index": mention["chunk_index"],
                "section_title": mention["section_title"],
                "chunk_snippet": mention["chunk_snippet"],
                "document_id": mention["document_id"],
                "document_title": mention["document_title"],
                "source_path": mention["source_path"],
                "mention_count": 0,
                "extraction_methods": set(),
            },
        )
        bucket["mention_count"] = int(bucket["mention_count"]) + 1
        bucket["extraction_methods"].add(mention["extraction_method"])

    top_chunks = []
    for item in chunks.values():
        source_path = str(item["source_path"])
        section_title = item["section_title"]
        top_chunks.append(
            {
                **item,
                "extraction_methods": sorted(item["extraction_methods"]),
                "source_ref": build_source_ref(source_path, str(section_title) if section_title else None),
                "markdown_ref": build_markdown_ref(
                    str(item["document_title"]),
                    source_path,
                    str(section_title) if section_title else None,
                ),
            }
        )

    return {
        **concept,
        "quality": concept_quality({mention["extraction_method"] for mention in mentions}, int(concept["mention_count"])),
        "mentions": mentions,
        "documents": sorted(document_summary, key=lambda item: -item["mention_count"]),
        "related_documents": sorted(document_summary, key=lambda item: -item["mention_count"]),
        "top_chunks": sorted(top_chunks, key=lambda item: (-int(item["mention_count"]), str(item["source_path"]))),
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
        WHERE e.entity_type = 'concept'
          AND (
              e.normalized_key IN ({placeholders})
              OR lower(replace(replace(em.mention_text, '_', ' '), '-', ' ')) IN ({placeholders})
          )
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


def concept_noise_report(connection: sqlite3.Connection, *, limit: int = 50) -> dict[str, object]:
    candidates = list_concepts(connection, entity_type="concept", quality="medium", limit=10000)
    noisy = [
        item
        for item in candidates
        if int(item["mention_count"]) <= 2
        and not set(item["extraction_methods"]).intersection(STRONG_CONCEPT_METHODS)
    ]
    noisy.sort(key=lambda item: (int(item["mention_count"]), item["canonical_name"]))
    return {
        "count": len(noisy),
        "concepts": noisy[:limit],
        "criteria": {
            "entity_type": "concept",
            "quality": "medium",
            "max_mention_count": 2,
            "strong_methods_excluded": sorted(STRONG_CONCEPT_METHODS),
        },
    }
