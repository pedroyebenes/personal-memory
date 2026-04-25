from __future__ import annotations

import sqlite3

from app.config import Settings
from app.models import SearchFilters
from app.retrieval.llm import LLMConfigurationError, synthesize_answer
from app.retrieval.hybrid_search import hybrid_search
from app.retrieval.query_rewrite import resolve_retrieval_query


def _build_sources(results) -> list[dict[str, object]]:
    sources = []
    for result in results:
        anchor = result.section_title.lower().replace(" ", "-") if result.section_title else None
        sources.append(
            {
                "document_title": result.document_title,
                "source_path": result.source_path,
                "chunk_id": str(result.chunk_id),
                "chunk_index": result.chunk_index,
                "section_title": result.section_title,
                "snippet": result.snippet,
                "source_ref": f"{result.source_path}#{anchor}" if anchor else result.source_path,
                "keyword_score": result.keyword_score,
                "semantic_score": result.semantic_score,
                "metadata_score": result.metadata_score,
                "final_score": result.final_score,
                "score_explanation": result.score_explanation,
            }
        )
    return sources


def _build_extractive_answer(results) -> str:
    evidence_lines = []
    for result in results:
        section = f" [{result.section_title}]" if result.section_title else ""
        evidence_lines.append(f"- {result.document_title}{section}: {result.snippet}")
    return "Relevant evidence:\n" + "\n".join(evidence_lines)


def _evidence_is_sufficient(results) -> bool:
    if not results:
        return False
    top_score = results[0].final_score
    return top_score >= 0.2 or len(results) >= 2


def answer_question(
    connection: sqlite3.Connection,
    query: str,
    settings: Settings,
    top_k: int = 5,
    use_llm: bool | None = None,
    use_query_rewrite: bool | None = None,
    filters: SearchFilters | None = None,
) -> dict[str, object]:
    retrieval_query, warnings = resolve_retrieval_query(query, settings, use_query_rewrite=use_query_rewrite)
    results = hybrid_search(connection, retrieval_query, settings, top_k=top_k, filters=filters)
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
        if _evidence_is_sufficient(results):
            try:
                answer = synthesize_answer(query, sources, settings)
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
