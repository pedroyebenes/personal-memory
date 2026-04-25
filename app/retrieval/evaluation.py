from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

from app.config import Settings
from app.retrieval.hybrid_search import hybrid_search


DEFAULT_CASE_PATHS = (
    Path("retrieval_eval.json"),
    Path("plan/retrieval_eval.json"),
)


def load_retrieval_cases(path: Path | None = None) -> list[dict[str, Any]]:
    candidate_paths = [path] if path else list(DEFAULT_CASE_PATHS)
    for candidate in candidate_paths:
        if candidate is None or not candidate.exists():
            continue
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            cases = payload.get("cases", [])
        else:
            cases = payload
        if not isinstance(cases, list):
            raise ValueError("retrieval eval cases must be a list or an object with a 'cases' list")
        return [case for case in cases if isinstance(case, dict)]
    return []


def evaluate_retrieval(
    connection: sqlite3.Connection,
    settings: Settings,
    *,
    cases_path: Path | None = None,
    top_k: int | None = None,
    use_rerank: bool | None = None,
    use_concept_boost: bool | None = None,
) -> dict[str, object]:
    cases = load_retrieval_cases(cases_path)
    return evaluate_retrieval_cases(
        connection,
        settings,
        cases,
        cases_path=cases_path,
        top_k=top_k,
        use_rerank=use_rerank,
        use_concept_boost=use_concept_boost,
    )


def evaluate_retrieval_cases(
    connection: sqlite3.Connection,
    settings: Settings,
    cases: list[dict[str, Any]],
    *,
    cases_path: Path | None = None,
    top_k: int | None = None,
    use_rerank: bool | None = None,
    use_concept_boost: bool | None = None,
) -> dict[str, object]:
    k = top_k or settings.top_k
    evaluated: list[dict[str, object]] = []
    passed = 0
    for index, case in enumerate(cases, start=1):
        query = str(case.get("query") or "").strip()
        expected_paths = [str(item) for item in case.get("expected_paths", [])]
        expected_terms = [str(item).lower() for item in case.get("expected_terms", [])]
        if not query:
            continue
        results = hybrid_search(
            connection,
            query,
            settings,
            top_k=k,
            use_rerank=use_rerank,
            use_concept_boost=use_concept_boost,
        )
        result_paths = [result.source_path for result in results]
        result_text = "\n".join([result.snippet for result in results]).lower()
        path_hit = not expected_paths or any(
            any(expected in actual for actual in result_paths)
            for expected in expected_paths
        )
        term_hit = not expected_terms or all(term in result_text for term in expected_terms)
        ok = bool(results) and path_hit and term_hit
        if ok:
            passed += 1
        evaluated.append(
            {
                "id": case.get("id", index),
                "query": query,
                "ok": ok,
                "expected_paths": expected_paths,
                "expected_terms": expected_terms,
                "top_paths": result_paths,
                "top_scores": [result.final_score for result in results],
            }
        )
    total = len(evaluated)
    return {
        "status": "no_cases" if total == 0 else ("passed" if passed == total else "failed"),
        "cases_path": str(cases_path) if cases_path else None,
        "top_k": k,
        "passed": passed,
        "failed": total - passed,
        "total": total,
        "cases": evaluated,
        "case_schema": {
            "cases": [
                {
                    "id": "north-star",
                    "query": "What is North Star?",
                    "expected_paths": ["project-note.md"],
                    "expected_terms": ["launch"],
                }
            ]
        },
    }
