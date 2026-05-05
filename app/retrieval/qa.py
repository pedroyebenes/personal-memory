from __future__ import annotations

import sqlite3
from typing import Any

from app.config import Settings
from app.models import SearchFilters
from app.retrieval.llm import LLMConfigurationError, synthesize_answer
from app.retrieval.hybrid_search import hybrid_search
from app.retrieval.query_rewrite import resolve_retrieval_query
from app.retrieval.sources import build_markdown_ref, build_source_ref

CONVERSATION_HISTORY_TURNS = 6
CONTEXTUAL_RETRIEVAL_TURNS = 3
CONTEXTUAL_RETRIEVAL_SOURCES_PER_TURN = 3
SOURCE_CONTEXT_WINDOW = 1
SOURCE_CONTEXT_CHAR_LIMIT = 3000


def _compact_text(value: object, limit: int = 240) -> str:
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _normalize_history_source(source: object) -> dict[str, object]:
    if not isinstance(source, dict):
        return {}
    normalized: dict[str, object] = {}
    for key in ("document_title", "source_path", "section_title", "snippet", "chunk_id"):
        text = _compact_text(source.get(key), limit=320)
        if text:
            normalized[key] = text
    try:
        if source.get("document_id") is not None:
            normalized["document_id"] = int(source["document_id"])
    except (TypeError, ValueError):
        pass
    return normalized


def _normalize_conversation_history(history: list[dict[str, object]] | None) -> list[dict[str, object]]:
    if not isinstance(history, list):
        return []
    normalized: list[dict[str, object]] = []
    for item in history[-CONVERSATION_HISTORY_TURNS:]:
        if not isinstance(item, dict):
            continue
        turn: dict[str, object] = {}
        question = _compact_text(item.get("question"), limit=400)
        answer = _compact_text(item.get("answer"), limit=800)
        answer_mode = _compact_text(item.get("answer_mode"), limit=80)
        if question:
            turn["question"] = question
        if answer:
            turn["answer"] = answer
        if answer_mode:
            turn["answer_mode"] = answer_mode
        raw_sources = item.get("sources", [])
        sources = []
        if isinstance(raw_sources, list):
            sources = [source for source in (_normalize_history_source(raw) for raw in raw_sources) if source]
        if sources:
            turn["sources"] = sources[:5]
        if turn:
            normalized.append(turn)
    return normalized


def _source_label(source: dict[str, object]) -> str:
    parts = [
        _compact_text(source.get("document_title"), limit=120),
        _compact_text(source.get("section_title"), limit=120),
        _compact_text(source.get("source_path"), limit=180),
    ]
    return " ".join(part for part in parts if part)


def _build_contextual_retrieval_query(retrieval_query: str, history: list[dict[str, object]]) -> str:
    base = retrieval_query.strip()
    context_lines: list[str] = []
    for turn in history[-CONTEXTUAL_RETRIEVAL_TURNS:]:
        question = _compact_text(turn.get("question"), limit=220)
        if question:
            context_lines.append(f"Previous question: {question}")
        sources = turn.get("sources", [])
        if not isinstance(sources, list):
            continue
        for source in sources[:CONTEXTUAL_RETRIEVAL_SOURCES_PER_TURN]:
            if not isinstance(source, dict):
                continue
            label = _source_label(source)
            if label:
                context_lines.append(f"Previous source: {label}")
    if not context_lines:
        return base
    return "\n".join([base, *context_lines])


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clip_context(text: str, limit: int = SOURCE_CONTEXT_CHAR_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _build_sources(results) -> list[dict[str, object]]:
    sources = []
    for result in results:
        source_ref = result.source_ref or build_source_ref(result.source_path, result.section_title)
        sources.append(
            {
                "document_title": result.document_title,
                "source_path": result.source_path,
                "document_id": result.document_id,
                "chunk_id": str(result.chunk_id),
                "chunk_index": result.chunk_index,
                "section_title": result.section_title,
                "snippet": result.snippet,
                "source_ref": source_ref,
                "markdown_ref": result.markdown_ref
                or build_markdown_ref(result.document_title, result.source_path, result.section_title),
                "keyword_score": result.keyword_score,
                "semantic_score": result.semantic_score,
                "metadata_score": result.metadata_score,
                "rerank_score": result.rerank_score,
                "final_score": result.final_score,
                "score_explanation": result.score_explanation,
                "matched_concepts": result.matched_concepts or [],
            }
        )
    return sources


def _sources_with_expanded_context(
    connection: sqlite3.Connection,
    sources: list[dict[str, object]],
) -> list[dict[str, object]]:
    expanded: list[dict[str, object]] = []
    for source in sources:
        source_copy = dict(source)
        chunk_id = _int_or_none(source.get("chunk_id"))
        if chunk_id is None:
            expanded.append(source_copy)
            continue
        row = connection.execute(
            "SELECT document_id, chunk_index FROM chunks WHERE id = ?",
            (chunk_id,),
        ).fetchone()
        if row is None:
            expanded.append(source_copy)
            continue
        document_id = int(row["document_id"])
        chunk_index = int(row["chunk_index"])
        source_copy["document_id"] = source_copy.get("document_id") or document_id
        context_rows = connection.execute(
            """
            SELECT id, chunk_index, section_title, text
            FROM chunks
            WHERE document_id = ?
              AND chunk_index BETWEEN ? AND ?
            ORDER BY chunk_index
            """,
            (document_id, chunk_index - SOURCE_CONTEXT_WINDOW, chunk_index + SOURCE_CONTEXT_WINDOW),
        ).fetchall()
        blocks = []
        for context_row in context_rows:
            marker = "Matched chunk" if int(context_row["id"]) == chunk_id else "Neighbor chunk"
            section = str(context_row["section_title"] or "No section title")
            blocks.append(
                "\n".join(
                    [
                        f"{marker} {int(context_row['chunk_index'])}",
                        f"Section: {section}",
                        str(context_row["text"]),
                    ]
                )
            )
        if blocks:
            source_copy["context"] = _clip_context("\n\n".join(blocks))
        expanded.append(source_copy)
    return expanded


def _build_extractive_answer(results) -> str:
    evidence_lines = []
    for result in results:
        section = f" [{result.section_title}]" if result.section_title else ""
        evidence_lines.append(f"- {result.document_title}{section}: {result.snippet}")
    return "Relevant evidence:\n" + "\n".join(evidence_lines)


def _evidence_is_sufficient(results, threshold: float = 0.2) -> bool:
    if not results:
        return False
    top_score = results[0].final_score
    return top_score >= threshold or len(results) >= 2


def answer_question(
    connection: sqlite3.Connection,
    query: str,
    settings: Settings,
    top_k: int = 5,
    use_llm: bool | None = None,
    use_query_rewrite: bool | None = None,
    filters: SearchFilters | None = None,
    use_rerank: bool | None = None,
    use_concept_boost: bool | None = None,
    conversation_history: list[dict[str, Any]] | None = None,
) -> dict[str, object]:
    history = _normalize_conversation_history(conversation_history)
    retrieval_query, warnings = resolve_retrieval_query(query, settings, use_query_rewrite=use_query_rewrite)
    retrieval_query = _build_contextual_retrieval_query(retrieval_query, history)
    results = hybrid_search(
        connection,
        retrieval_query,
        settings,
        top_k=top_k,
        filters=filters,
        use_rerank=use_rerank,
        use_concept_boost=use_concept_boost,
    )
    if not results:
        return {
            "question": query,
            "retrieval_query": retrieval_query,
            "answer": "No relevant evidence found.",
            "sources": [],
            "answer_mode": "extractive",
            "warnings": warnings + ["retrieval returned no evidence"],
            "provider": settings.llm_provider,
            "model": settings.get_synthesis_model_name(),
        }

    sources = _build_sources(results)
    should_use_llm = settings.enable_llm_synthesis if use_llm is None else use_llm
    if should_use_llm:
        if _evidence_is_sufficient(results, threshold=settings.evidence_sufficiency_threshold):
            try:
                llm_sources = _sources_with_expanded_context(connection, sources)
                answer = synthesize_answer(query, llm_sources, settings, conversation_history=history)
                return {
                    "question": query,
                    "retrieval_query": retrieval_query,
                    "answer": answer,
                    "sources": sources,
                    "answer_mode": "llm_synthesis",
                    "provider": settings.llm_provider,
                    "model": settings.get_synthesis_model_name(),
                    "warnings": warnings,
                }
            except LLMConfigurationError as exc:
                warnings.append(str(exc))
            except RuntimeError as exc:
                warnings.append(f"LLM synthesis failed: {exc}")
        else:
            warnings.append("evidence too weak for LLM synthesis; returned extractive answer instead")

    return {
        "question": query,
        "retrieval_query": retrieval_query,
        "answer": _build_extractive_answer(results),
        "sources": sources,
        "answer_mode": "extractive",
        "warnings": warnings,
        "provider": settings.llm_provider,
        "model": settings.get_synthesis_model_name(),
    }
