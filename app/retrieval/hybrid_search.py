from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from app.config import Settings
from app.models import RetrievalResult, SearchFilters
from app.retrieval.keyword_search import keyword_search
from app.retrieval.rerank import rerank_results
from app.retrieval.snippets import extract_snippet, query_terms
from app.retrieval.semantic_search import semantic_search


def _normalize_filters(filters: SearchFilters | None) -> SearchFilters:
    return filters or SearchFilters()


def _load_chunk_metadata(connection: sqlite3.Connection, chunk_ids: set[int]) -> dict[int, dict[str, object]]:
    if not chunk_ids:
        return {}

    placeholders = ", ".join("?" for _ in chunk_ids)
    rows = connection.execute(
        f"""
        SELECT
            c.id AS chunk_id,
            c.text,
            d.source_path,
            d.title,
            d.last_modified,
            GROUP_CONCAT(DISTINCT dt.tag) AS tags,
            GROUP_CONCAT(DISTINCT da.alias) AS aliases
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        LEFT JOIN document_tags dt ON dt.document_id = d.id
        LEFT JOIN document_aliases da ON da.document_id = d.id
        WHERE c.id IN ({placeholders})
        GROUP BY c.id, c.text, d.source_path, d.title, d.last_modified
        """,
        tuple(chunk_ids),
    ).fetchall()
    metadata: dict[int, dict[str, object]] = {}
    for row in rows:
        metadata[int(row["chunk_id"])] = {
            "text": row["text"],
            "source_path": row["source_path"],
            "title": row["title"],
            "last_modified": row["last_modified"],
            "tags": {item.strip().lower() for item in str(row["tags"] or "").split(",") if item.strip()},
            "aliases": {item.strip().lower() for item in str(row["aliases"] or "").split(",") if item.strip()},
        }
    return metadata


def _matches_filters(result: RetrievalResult, filters: SearchFilters, metadata: dict[int, dict[str, object]]) -> bool:
    if not (filters.tags or filters.aliases or filters.path_prefix or filters.date_from or filters.date_to):
        return True
    item = metadata.get(result.chunk_id, {})
    result_path = str(item.get("source_path") or result.source_path)
    last_modified = str(item.get("last_modified") or "")
    item_tags = item.get("tags", set())
    item_aliases = item.get("aliases", set())
    filter_tags = {tag.lower() for tag in filters.tags}
    filter_aliases = {alias.lower() for alias in filters.aliases}

    if filters.path_prefix and not result_path.startswith(filters.path_prefix):
        return False
    if filters.date_from and last_modified < filters.date_from:
        return False
    if filters.date_to and last_modified > filters.date_to:
        return False
    if filter_tags and not filter_tags.issubset(item_tags):
        return False
    if filter_aliases and not filter_aliases.intersection(item_aliases):
        return False
    return True


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _metadata_score(
    result: RetrievalResult,
    metadata: dict[str, object],
    terms: list[str],
    now: datetime,
) -> tuple[float, dict[str, object]]:
    title = str(metadata.get("title") or result.document_title).lower()
    section = (result.section_title or "").lower()
    source_path = str(metadata.get("source_path") or result.source_path)
    filename = Path(source_path).stem.replace("_", " ").replace("-", " ").lower()
    tags = metadata.get("tags", set())
    aliases = metadata.get("aliases", set())
    last_modified = _parse_datetime(metadata.get("last_modified"))

    factors: dict[str, float] = {}
    if terms:
        if any(term in title or term in filename for term in terms):
            factors["title_or_filename_match"] = 0.08
        if section and any(term in section for term in terms):
            factors["heading_match"] = 0.06
        if any(any(term in alias for term in terms) for alias in aliases):
            factors["alias_match"] = 0.08
        if any(any(term in tag for term in terms) for tag in tags):
            factors["tag_match"] = 0.05

    if last_modified is not None:
        if last_modified.tzinfo is None:
            last_modified = last_modified.replace(tzinfo=timezone.utc)
        age_days = max(0, (now - last_modified.astimezone(timezone.utc)).days)
        if age_days <= 30:
            factors["recency"] = 0.04
        elif age_days <= 180:
            factors["recency"] = 0.025
        elif age_days <= 365:
            factors["recency"] = 0.01

    metadata_score = round(min(sum(factors.values()), 0.25), 6)
    explanation: dict[str, object] = {
        "keyword_score": result.keyword_score,
        "semantic_score": result.semantic_score,
        "metadata_score": metadata_score,
        "metadata_factors": factors,
        "rerank_score": 0.0,
        "rerank_factors": {},
    }
    return metadata_score, explanation


def hybrid_search(
    connection: sqlite3.Connection,
    query: str,
    settings: Settings,
    top_k: int = 5,
    semantic_weight: float = 0.7,
    keyword_weight: float = 0.3,
    filters: SearchFilters | None = None,
    use_rerank: bool | None = None,
) -> list[RetrievalResult]:
    filters = _normalize_filters(filters)
    should_rerank = settings.enable_reranking if use_rerank is None else use_rerank
    terms = query_terms(query)
    keyword_results = {result.chunk_id: result for result in keyword_search(connection, query, top_k=top_k * 2)}
    semantic_results = {result.chunk_id: result for result in semantic_search(connection, query, settings, top_k=top_k * 2)}
    metadata = _load_chunk_metadata(connection, set(keyword_results) | set(semantic_results))
    now = datetime.now(timezone.utc)

    merged: list[RetrievalResult] = []
    for chunk_id in set(keyword_results) | set(semantic_results):
        keyword_result = keyword_results.get(chunk_id)
        semantic_result = semantic_results.get(chunk_id)
        base = semantic_result or keyword_result
        assert base is not None
        keyword_score = keyword_result.keyword_score if keyword_result else None
        semantic_score = semantic_result.semantic_score if semantic_result else None
        base_score = (semantic_score or 0.0) * semantic_weight + (keyword_score or 0.0) * keyword_weight
        metadata_score, score_explanation = _metadata_score(base, metadata.get(chunk_id, {}), terms, now)
        final_score = base_score + metadata_score
        score_explanation["base_score"] = base_score
        score_explanation["final_score"] = final_score
        chunk_text = str(metadata.get(chunk_id, {}).get("text") or base.snippet)
        merged.append(
            RetrievalResult(
                document_title=base.document_title,
                source_path=base.source_path,
                chunk_id=base.chunk_id,
                chunk_index=base.chunk_index,
                section_title=base.section_title,
                snippet=extract_snippet(chunk_text, query),
                keyword_score=keyword_score,
                semantic_score=semantic_score,
                final_score=final_score,
                metadata_score=metadata_score,
                rerank_score=0.0,
                score_explanation=score_explanation,
            )
        )
    merged = [item for item in merged if _matches_filters(item, filters, metadata)]
    merged.sort(key=lambda item: item.final_score, reverse=True)
    if should_rerank:
        chunk_texts = {chunk_id: str(item.get("text") or "") for chunk_id, item in metadata.items()}
        merged = rerank_results(merged, query, chunk_texts)
    return merged[:top_k]
