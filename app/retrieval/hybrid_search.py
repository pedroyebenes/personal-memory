from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from app.config import Settings
from app.models import RetrievalResult, SearchFilters
from app.retrieval.concept_search import (
    candidate_keys_from_terms,
    chunks_with_concepts,
    find_concepts_for_terms,
)
from app.retrieval.keyword_search import keyword_search
from app.retrieval.rerank import rerank_results
from app.retrieval.snippets import extract_snippet, query_terms
from app.retrieval.semantic_search import semantic_search
from app.retrieval.sources import build_markdown_ref, build_source_ref

CONCEPT_BOOST_WEIGHT = 0.06  # default; overridden per-request by Settings.concept_boost_weight
EXACT_CONCEPT_BOOST_STEP = 0.08
EXACT_CONCEPT_BOOST_MAX = 0.15  # default; overridden per-request by Settings.concept_boost_exact_max


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


def _load_exact_key_entities(connection: sqlite3.Connection, keys: set[str]) -> dict[int, str]:
    if not keys:
        return {}
    placeholders = ",".join("?" for _ in keys)
    rows = connection.execute(
        f"""
        SELECT id, canonical_name
        FROM entities
        WHERE entity_type = 'concept' AND normalized_key IN ({placeholders})
        """,
        tuple(keys),
    ).fetchall()
    return {int(r["id"]): str(r["canonical_name"]) for r in rows}


def _apply_exact_concept_boost(
    connection: sqlite3.Connection,
    results: list[RetrievalResult],
    terms: list[str],
    *,
    step: float = EXACT_CONCEPT_BOOST_STEP,
    max_boost: float = EXACT_CONCEPT_BOOST_MAX,
) -> None:
    if not results or not terms:
        return
    keys = candidate_keys_from_terms(terms)
    entity_map = _load_exact_key_entities(connection, keys)
    entity_ids = set(entity_map)
    chunk_ids = {result.chunk_id for result in results}
    matches = chunks_with_concepts(connection, chunk_ids, entity_ids) if entity_ids else {}
    for result in results:
        explanation = result.score_explanation or {}
        if not entity_map:
            explanation["exact_concept_boost"] = 0.0
            explanation["exact_concept_matches"] = []
            result.score_explanation = explanation
            continue
        hit_entities = matches.get(result.chunk_id, set()).intersection(entity_ids)
        if not hit_entities:
            explanation["exact_concept_boost"] = 0.0
            explanation["exact_concept_matches"] = []
            result.score_explanation = explanation
            continue
        raw = len(hit_entities) * step
        boost = round(min(raw, max_boost), 6)
        result.final_score += boost
        exact_matches = [
            {"id": entity_id, "canonical_name": entity_map[entity_id]} for entity_id in sorted(hit_entities)
        ]
        explanation["exact_concept_boost"] = boost
        explanation["exact_concept_matches"] = exact_matches
        explanation["final_score"] = result.final_score
        result.score_explanation = explanation


def _apply_concept_boost(
    connection: sqlite3.Connection,
    results: list[RetrievalResult],
    terms: list[str],
    *,
    weight: float = CONCEPT_BOOST_WEIGHT,
) -> None:
    if not results or not terms:
        return
    matched_concepts = find_concepts_for_terms(connection, terms)
    if not matched_concepts:
        return
    entity_ids = {int(item["id"]) for item in matched_concepts}
    chunk_ids = {result.chunk_id for result in results}
    matches = chunks_with_concepts(connection, chunk_ids, entity_ids)
    if not matches:
        return
    by_id = {int(item["id"]): item for item in matched_concepts}
    for result in results:
        hit_entities = matches.get(result.chunk_id)
        if not hit_entities:
            continue
        boost = round(min(len(hit_entities) * weight, 0.18), 6)
        result.final_score += boost
        concept_matches = [
            {"id": entity_id, "canonical_name": by_id[entity_id]["canonical_name"]}
            for entity_id in sorted(hit_entities)
            if entity_id in by_id
        ]
        result.matched_concepts = concept_matches
        explanation = result.score_explanation or {}
        explanation["concept_boost"] = boost
        explanation["concept_matches"] = concept_matches
        explanation["final_score"] = result.final_score
        result.score_explanation = explanation


def hybrid_search(
    connection: sqlite3.Connection,
    query: str,
    settings: Settings,
    top_k: int = 5,
    semantic_weight: float = 0.7,
    keyword_weight: float = 0.3,
    filters: SearchFilters | None = None,
    use_rerank: bool | None = None,
    use_concept_boost: bool | None = None,
    debug_scores: bool = False,
) -> list[RetrievalResult]:
    filters = _normalize_filters(filters)
    should_rerank = settings.enable_reranking if use_rerank is None else use_rerank
    should_boost_concepts = (
        settings.enable_concept_boost if use_concept_boost is None else use_concept_boost
    )
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
                matched_concepts=[],
                source_ref=build_source_ref(base.source_path, base.section_title),
                markdown_ref=build_markdown_ref(base.document_title, base.source_path, base.section_title),
            )
        )
    merged = [item for item in merged if _matches_filters(item, filters, metadata)]
    if should_boost_concepts:
        for item in merged:
            explanation = item.score_explanation or {}
            explanation.setdefault("concept_boost", 0.0)
            explanation.setdefault("exact_concept_boost", 0.0)
            explanation.setdefault("concept_matches", [])
            explanation.setdefault("exact_concept_matches", [])
            item.score_explanation = explanation
        _apply_exact_concept_boost(
            connection, merged, terms,
            step=EXACT_CONCEPT_BOOST_STEP,
            max_boost=settings.concept_boost_exact_max,
        )
        _apply_concept_boost(connection, merged, terms, weight=settings.concept_boost_weight)
    merged.sort(key=lambda item: item.final_score, reverse=True)
    if should_rerank:
        chunk_texts = {chunk_id: str(item.get("text") or "") for chunk_id, item in metadata.items()}
        merged = rerank_results(merged, query, chunk_texts, max_boost=settings.rerank_max_boost)
    if debug_scores:
        for item in merged:
            explanation = item.score_explanation or {}
            explanation["fusion_weights"] = {
                "semantic_weight": semantic_weight,
                "keyword_weight": keyword_weight,
            }
            item.score_explanation = explanation
    # Clamp to [0, 1] so scores remain interpretable regardless of how many boosts fire.
    for item in merged:
        item.final_score = round(max(0.0, min(1.0, item.final_score)), 6)
        if item.score_explanation:
            item.score_explanation["final_score"] = item.final_score
    return merged[:top_k]
