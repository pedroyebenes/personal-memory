from __future__ import annotations

import re

from app.models import RetrievalResult
from app.retrieval.snippets import query_terms


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _term_positions(text: str, terms: list[str]) -> list[int]:
    positions: list[int] = []
    for term in terms:
        position = text.find(term)
        if position >= 0:
            positions.append(position)
    return positions


def rerank_results(
    results: list[RetrievalResult],
    query: str,
    chunk_texts: dict[int, str],
    *,
    max_boost: float = 0.18,
) -> list[RetrievalResult]:
    terms = query_terms(query)
    if not terms:
        return results

    query_text = _compact(query)
    for result in results:
        haystack = _compact(" ".join([result.document_title, result.section_title or "", chunk_texts.get(result.chunk_id, result.snippet)]))
        matched_terms = [term for term in terms if term in haystack]
        coverage = len(matched_terms) / len(terms)
        factors: dict[str, float] = {}
        if query_text and query_text in haystack:
            factors["exact_phrase"] = 0.08
        if coverage:
            factors["term_coverage"] = coverage * 0.06
        positions = _term_positions(haystack, matched_terms)
        if len(positions) >= 2 and max(positions) - min(positions) <= 180:
            factors["term_proximity"] = 0.04

        rerank_score = round(min(sum(factors.values()), max_boost), 6)
        result.rerank_score = rerank_score
        result.final_score += rerank_score
        explanation = result.score_explanation or {}
        explanation["rerank_score"] = rerank_score
        explanation["rerank_factors"] = factors
        explanation["final_score"] = result.final_score
        result.score_explanation = explanation

    results.sort(key=lambda item: item.final_score, reverse=True)
    return results
