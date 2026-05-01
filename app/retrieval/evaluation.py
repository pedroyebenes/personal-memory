from __future__ import annotations

import json
import math
from pathlib import Path
import sqlite3
from statistics import mean
from typing import Any, Iterable

from app.config import Settings
from app.models import RetrievalResult
from app.retrieval.hybrid_search import hybrid_search


DEFAULT_CASE_PATHS = (
    Path("retrieval_eval.json"),
    Path("plan/retrieval_eval.json"),
)

# Bundled golden case sets keyed by name. The fixture set is tied to
# tests/fixtures/vault and lets `personal-memory eval retrieval --builtin fixture`
# work out of the box on a freshly ingested fixture vault.
_BUILTIN_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "golden"
BUILTIN_CASE_SETS = {
    "fixture": _BUILTIN_DIR / "fixture_vault_cases.json",
}

DEFAULT_REGRESSION_THRESHOLD = 0.02

# Preset retrieval configurations used by the multi-config comparison report.
COMPARE_PRESETS: tuple[tuple[str, dict[str, bool | None]], ...] = (
    ("hybrid", {"use_rerank": False, "use_concept_boost": False}),
    ("hybrid_rerank", {"use_rerank": True, "use_concept_boost": False}),
    ("hybrid_concepts", {"use_rerank": False, "use_concept_boost": True}),
    ("hybrid_full", {"use_rerank": True, "use_concept_boost": True}),
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


def load_builtin_cases(name: str) -> list[dict[str, Any]]:
    if name not in BUILTIN_CASE_SETS:
        raise ValueError(f"Unknown builtin case set: {name}. Known: {sorted(BUILTIN_CASE_SETS)}")
    return load_retrieval_cases(BUILTIN_CASE_SETS[name])


def _result_is_relevant(
    result: RetrievalResult,
    expected_paths: list[str],
    expected_terms: list[str],
) -> bool:
    if expected_paths:
        return any(expected in result.source_path for expected in expected_paths)
    if expected_terms:
        snippet = (result.snippet or "").lower()
        return all(term in snippet for term in expected_terms)
    return False


def _compute_case_metrics(
    results: list[RetrievalResult],
    expected_paths: list[str],
    expected_terms: list[str],
    k: int,
) -> dict[str, float]:
    """Compute hit@k, MRR@k, NDCG@k, recall@k for a single case.

    Relevance is binary, derived from `expected_paths` (substring match against
    `source_path`) when present, otherwise from `expected_terms` (all terms must
    appear in the snippet).
    """
    top = results[:k]
    relevant_flags = [_result_is_relevant(r, expected_paths, expected_terms) for r in top]

    mrr = 0.0
    for index, is_rel in enumerate(relevant_flags):
        if is_rel:
            mrr = 1.0 / (index + 1)
            break

    dcg = sum(
        (1.0 / math.log2(index + 2)) if is_rel else 0.0
        for index, is_rel in enumerate(relevant_flags)
    )
    if expected_paths:
        ideal_count = min(len(expected_paths), k)
    elif expected_terms:
        ideal_count = 1
    else:
        ideal_count = 0
    if ideal_count > 0:
        ideal_dcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_count))
        ndcg = dcg / ideal_dcg if ideal_dcg > 0 else 0.0
    else:
        ndcg = 0.0

    if expected_paths:
        matched: set[str] = set()
        for result in top:
            for expected in expected_paths:
                if expected in result.source_path:
                    matched.add(expected)
        recall = len(matched) / len(expected_paths)
    elif expected_terms:
        recall = 1.0 if any(relevant_flags) else 0.0
    else:
        recall = 0.0

    hit = 1.0 if any(relevant_flags) else 0.0
    return {
        "hit_at_k": round(hit, 6),
        "mrr_at_k": round(mrr, 6),
        "ndcg_at_k": round(ndcg, 6),
        "recall_at_k": round(recall, 6),
    }


def _aggregate_metrics(per_case: list[dict[str, float]]) -> dict[str, float]:
    if not per_case:
        return {"hit_at_k": 0.0, "mrr_at_k": 0.0, "ndcg_at_k": 0.0, "recall_at_k": 0.0}
    keys = ("hit_at_k", "mrr_at_k", "ndcg_at_k", "recall_at_k")
    return {key: round(mean(case[key] for case in per_case), 6) for key in keys}


def evaluate_retrieval(
    connection: sqlite3.Connection,
    settings: Settings,
    *,
    cases_path: Path | None = None,
    builtin: str | None = None,
    top_k: int | None = None,
    use_rerank: bool | None = None,
    use_concept_boost: bool | None = None,
) -> dict[str, object]:
    if builtin:
        cases = load_builtin_cases(builtin)
        cases_label: str = f"builtin:{builtin}"
    else:
        cases = load_retrieval_cases(cases_path)
        cases_label = str(cases_path) if cases_path else ""
    return evaluate_retrieval_cases(
        connection,
        settings,
        cases,
        cases_path=cases_path,
        cases_label=cases_label or None,
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
    cases_label: str | None = None,
    top_k: int | None = None,
    use_rerank: bool | None = None,
    use_concept_boost: bool | None = None,
) -> dict[str, object]:
    k = top_k or settings.top_k
    evaluated: list[dict[str, object]] = []
    metric_records: list[dict[str, float]] = []
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
        metrics = _compute_case_metrics(results, expected_paths, expected_terms, k)
        if expected_paths or expected_terms:
            metric_records.append(metrics)
        evaluated.append(
            {
                "id": case.get("id", index),
                "query": query,
                "ok": ok,
                "expected_paths": expected_paths,
                "expected_terms": expected_terms,
                "top_paths": result_paths,
                "top_scores": [result.final_score for result in results],
                "metrics": metrics,
            }
        )
    total = len(evaluated)
    aggregate = _aggregate_metrics(metric_records)
    label = cases_label if cases_label is not None else (str(cases_path) if cases_path else None)
    return {
        "status": "no_cases" if total == 0 else ("passed" if passed == total else "failed"),
        "cases_path": label,
        "top_k": k,
        "passed": passed,
        "failed": total - passed,
        "total": total,
        "metrics": aggregate,
        "metric_cases_counted": len(metric_records),
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


def evaluate_retrieval_compare(
    connection: sqlite3.Connection,
    settings: Settings,
    *,
    cases_path: Path | None = None,
    builtin: str | None = None,
    top_k: int | None = None,
    presets: Iterable[tuple[str, dict[str, bool | None]]] = COMPARE_PRESETS,
) -> dict[str, object]:
    """Run several retrieval configurations against the same case set."""
    if builtin:
        cases = load_builtin_cases(builtin)
        cases_label: str = f"builtin:{builtin}"
    else:
        cases = load_retrieval_cases(cases_path)
        cases_label = str(cases_path) if cases_path else ""
    runs: list[dict[str, object]] = []
    for name, overrides in presets:
        payload = evaluate_retrieval_cases(
            connection,
            settings,
            cases,
            cases_path=cases_path,
            cases_label=cases_label or None,
            top_k=top_k,
            use_rerank=overrides.get("use_rerank"),
            use_concept_boost=overrides.get("use_concept_boost"),
        )
        runs.append(
            {
                "config": name,
                "overrides": overrides,
                "status": payload["status"],
                "passed": payload["passed"],
                "failed": payload["failed"],
                "total": payload["total"],
                "metrics": payload["metrics"],
                "metric_cases_counted": payload["metric_cases_counted"],
            }
        )
    return {
        "cases_path": cases_label or (str(cases_path) if cases_path else None),
        "top_k": top_k or settings.top_k,
        "runs": runs,
    }


def diff_against_baseline(
    current: dict[str, object],
    baseline: dict[str, object],
    *,
    threshold: float = DEFAULT_REGRESSION_THRESHOLD,
) -> dict[str, object]:
    """Compare a current eval payload against a saved baseline.

    `regressed` is True iff any aggregate metric drops by more than `threshold`
    versus the baseline. Per-case regressions are also surfaced for cases that
    appear in both runs (matched by `id`).
    """
    current_metrics = current.get("metrics", {}) or {}
    baseline_metrics = baseline.get("metrics", {}) or {}

    aggregate_diff: dict[str, dict[str, float | bool]] = {}
    aggregate_regressed = False
    for key in ("hit_at_k", "mrr_at_k", "ndcg_at_k", "recall_at_k"):
        current_value = float(current_metrics.get(key, 0.0))
        baseline_value = float(baseline_metrics.get(key, 0.0))
        delta = round(current_value - baseline_value, 6)
        regressed = delta < -threshold
        if regressed:
            aggregate_regressed = True
        aggregate_diff[key] = {
            "current": round(current_value, 6),
            "baseline": round(baseline_value, 6),
            "delta": delta,
            "regressed": regressed,
        }

    baseline_cases = {
        case.get("id"): case for case in baseline.get("cases", []) if isinstance(case, dict)
    }
    case_diffs: list[dict[str, object]] = []
    for case in current.get("cases", []) or []:
        if not isinstance(case, dict):
            continue
        case_id = case.get("id")
        baseline_case = baseline_cases.get(case_id)
        if not isinstance(baseline_case, dict):
            continue
        per_case_diff: dict[str, dict[str, float | bool]] = {}
        regressed_case = False
        cur_metrics = case.get("metrics", {}) or {}
        base_metrics = baseline_case.get("metrics", {}) or {}
        for metric_key in ("hit_at_k", "mrr_at_k", "ndcg_at_k", "recall_at_k"):
            cur_value = float(cur_metrics.get(metric_key, 0.0))
            base_value = float(base_metrics.get(metric_key, 0.0))
            delta = round(cur_value - base_value, 6)
            regressed = delta < -threshold
            if regressed:
                regressed_case = True
            per_case_diff[metric_key] = {
                "current": round(cur_value, 6),
                "baseline": round(base_value, 6),
                "delta": delta,
                "regressed": regressed,
            }
        if regressed_case:
            case_diffs.append({"id": case_id, "metrics": per_case_diff})

    return {
        "threshold": threshold,
        "regressed": aggregate_regressed,
        "aggregate": aggregate_diff,
        "regressed_cases": case_diffs,
    }
