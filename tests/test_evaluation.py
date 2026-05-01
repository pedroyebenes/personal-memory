from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from app.config import Settings
from app.ingest.register import ingest_vault
from app.models import RetrievalResult
from app.retrieval.evaluation import (
    BUILTIN_CASE_SETS,
    DEFAULT_REGRESSION_THRESHOLD,
    _aggregate_metrics,
    _compute_case_metrics,
    diff_against_baseline,
    evaluate_retrieval,
    evaluate_retrieval_cases,
    evaluate_retrieval_compare,
    load_builtin_cases,
)


def _make_result(chunk_id: int, source_path: str, snippet: str = "") -> RetrievalResult:
    return RetrievalResult(
        document_title="t",
        source_path=source_path,
        chunk_id=chunk_id,
        chunk_index=0,
        section_title=None,
        snippet=snippet,
        keyword_score=None,
        semantic_score=None,
        final_score=0.0,
    )


class TestComputeCaseMetrics:
    def test_perfect_ranking(self) -> None:
        results = [
            _make_result(1, "vault/a.md"),
            _make_result(2, "vault/b.md"),
            _make_result(3, "vault/c.md"),
        ]
        metrics = _compute_case_metrics(results, ["a.md", "b.md"], [], k=3)
        # Both relevant docs are in top-2, so recall=1.0, hit=1.0, MRR@k=1.0
        assert metrics["hit_at_k"] == 1.0
        assert metrics["mrr_at_k"] == 1.0
        assert metrics["recall_at_k"] == 1.0
        # NDCG: dcg = 1/log2(2) + 1/log2(3) = 1 + 0.6309
        # ideal = same since ideal_count = min(2, 3) = 2
        expected_ndcg = (1.0 + 1.0 / math.log2(3)) / (1.0 + 1.0 / math.log2(3))
        assert metrics["ndcg_at_k"] == pytest.approx(expected_ndcg, abs=1e-5)

    def test_relevant_buried_at_position_three(self) -> None:
        results = [
            _make_result(1, "vault/x.md"),
            _make_result(2, "vault/y.md"),
            _make_result(3, "vault/a.md"),
        ]
        metrics = _compute_case_metrics(results, ["a.md"], [], k=3)
        assert metrics["hit_at_k"] == 1.0
        assert metrics["mrr_at_k"] == pytest.approx(1.0 / 3, abs=1e-5)
        # ideal_count = min(1, 3) = 1, ideal_dcg = 1.0
        # dcg = 1 / log2(4) = 0.5
        assert metrics["ndcg_at_k"] == pytest.approx(0.5, abs=1e-5)
        assert metrics["recall_at_k"] == 1.0

    def test_no_relevant_returns_zero(self) -> None:
        results = [_make_result(1, "vault/x.md"), _make_result(2, "vault/y.md")]
        metrics = _compute_case_metrics(results, ["target.md"], [], k=3)
        assert metrics == {
            "hit_at_k": 0.0,
            "mrr_at_k": 0.0,
            "ndcg_at_k": 0.0,
            "recall_at_k": 0.0,
        }

    def test_terms_only_relevance(self) -> None:
        results = [
            _make_result(1, "vault/a.md", snippet="Nothing here."),
            _make_result(2, "vault/b.md", snippet="The launch plan is set."),
        ]
        metrics = _compute_case_metrics(results, [], ["launch"], k=3)
        assert metrics["hit_at_k"] == 1.0
        assert metrics["mrr_at_k"] == pytest.approx(0.5, abs=1e-5)
        assert metrics["recall_at_k"] == 1.0

    def test_empty_labels_yield_zero(self) -> None:
        results = [_make_result(1, "vault/a.md")]
        metrics = _compute_case_metrics(results, [], [], k=3)
        assert metrics == {
            "hit_at_k": 0.0,
            "mrr_at_k": 0.0,
            "ndcg_at_k": 0.0,
            "recall_at_k": 0.0,
        }

    def test_partial_recall_with_two_expected(self) -> None:
        results = [
            _make_result(1, "vault/a.md"),
            _make_result(2, "vault/x.md"),
            _make_result(3, "vault/y.md"),
        ]
        metrics = _compute_case_metrics(results, ["a.md", "b.md"], [], k=3)
        # Only one of two expected paths is hit
        assert metrics["recall_at_k"] == 0.5
        assert metrics["hit_at_k"] == 1.0
        assert metrics["mrr_at_k"] == 1.0


class TestAggregate:
    def test_aggregate_averages_all_metrics(self) -> None:
        per_case = [
            {"hit_at_k": 1.0, "mrr_at_k": 1.0, "ndcg_at_k": 1.0, "recall_at_k": 1.0},
            {"hit_at_k": 0.0, "mrr_at_k": 0.0, "ndcg_at_k": 0.0, "recall_at_k": 0.0},
        ]
        agg = _aggregate_metrics(per_case)
        assert agg == {
            "hit_at_k": 0.5,
            "mrr_at_k": 0.5,
            "ndcg_at_k": 0.5,
            "recall_at_k": 0.5,
        }

    def test_aggregate_empty(self) -> None:
        assert _aggregate_metrics([]) == {
            "hit_at_k": 0.0,
            "mrr_at_k": 0.0,
            "ndcg_at_k": 0.0,
            "recall_at_k": 0.0,
        }


class TestBaselineDiff:
    def test_no_regression_when_metrics_unchanged(self) -> None:
        payload = {
            "metrics": {"hit_at_k": 1.0, "mrr_at_k": 0.8, "ndcg_at_k": 0.9, "recall_at_k": 0.7},
            "cases": [],
        }
        diff = diff_against_baseline(payload, payload)
        assert diff["regressed"] is False
        for entry in diff["aggregate"].values():
            assert entry["regressed"] is False
            assert entry["delta"] == 0.0

    def test_regression_detected_above_threshold(self) -> None:
        current = {
            "metrics": {"hit_at_k": 0.5, "mrr_at_k": 0.5, "ndcg_at_k": 0.5, "recall_at_k": 0.5},
            "cases": [],
        }
        baseline = {
            "metrics": {"hit_at_k": 1.0, "mrr_at_k": 1.0, "ndcg_at_k": 1.0, "recall_at_k": 1.0},
            "cases": [],
        }
        diff = diff_against_baseline(current, baseline, threshold=DEFAULT_REGRESSION_THRESHOLD)
        assert diff["regressed"] is True
        assert all(entry["regressed"] for entry in diff["aggregate"].values())

    def test_small_drop_within_threshold_is_ok(self) -> None:
        current = {"metrics": {"hit_at_k": 0.99}, "cases": []}
        baseline = {"metrics": {"hit_at_k": 1.0}, "cases": []}
        diff = diff_against_baseline(current, baseline, threshold=0.02)
        assert diff["regressed"] is False
        assert diff["aggregate"]["hit_at_k"]["regressed"] is False

    def test_per_case_regression_surfaces(self) -> None:
        current = {
            "metrics": {"hit_at_k": 1.0, "mrr_at_k": 1.0, "ndcg_at_k": 1.0, "recall_at_k": 1.0},
            "cases": [
                {
                    "id": "north-star",
                    "metrics": {"hit_at_k": 0.0, "mrr_at_k": 0.0, "ndcg_at_k": 0.0, "recall_at_k": 0.0},
                }
            ],
        }
        baseline = {
            "metrics": {"hit_at_k": 1.0, "mrr_at_k": 1.0, "ndcg_at_k": 1.0, "recall_at_k": 1.0},
            "cases": [
                {
                    "id": "north-star",
                    "metrics": {"hit_at_k": 1.0, "mrr_at_k": 1.0, "ndcg_at_k": 1.0, "recall_at_k": 1.0},
                }
            ],
        }
        diff = diff_against_baseline(current, baseline, threshold=0.02)
        # aggregate matches; per-case shows regression even if aggregate didn't change
        assert diff["regressed"] is False
        assert any(entry["id"] == "north-star" for entry in diff["regressed_cases"])


class TestBuiltinCases:
    def test_builtin_fixture_cases_load(self) -> None:
        cases = load_builtin_cases("fixture")
        assert cases
        assert all("query" in case for case in cases)

    def test_unknown_builtin_raises(self) -> None:
        with pytest.raises(ValueError):
            load_builtin_cases("does-not-exist")

    def test_builtin_set_paths_exist(self) -> None:
        for path in BUILTIN_CASE_SETS.values():
            assert path.exists(), f"Bundled golden case file missing: {path}"


class TestIntegration:
    def test_evaluate_retrieval_uses_builtin_against_fixture_vault(
        self, connection, fixture_vault: Path, settings: Settings
    ) -> None:
        ingest_vault(connection, fixture_vault, settings)
        payload = evaluate_retrieval(connection, settings, builtin="fixture", top_k=5)
        # Built-in fixture cases must succeed against the fixture vault. If this
        # ever stops being true, the regression check below would be silent —
        # so assert pass/fail bookkeeping plus aggregate metrics presence here.
        assert payload["total"] >= 1
        assert payload["status"] != "no_cases"
        assert payload["metrics"]["hit_at_k"] > 0
        assert payload["metric_cases_counted"] >= 1
        for case in payload["cases"]:
            assert "metrics" in case
            assert set(case["metrics"]) == {"hit_at_k", "mrr_at_k", "ndcg_at_k", "recall_at_k"}

    def test_compare_runs_multiple_configs(
        self, connection, fixture_vault: Path, settings: Settings
    ) -> None:
        ingest_vault(connection, fixture_vault, settings)
        payload = evaluate_retrieval_compare(
            connection, settings, builtin="fixture", top_k=3
        )
        assert {run["config"] for run in payload["runs"]} == {
            "hybrid",
            "hybrid_rerank",
            "hybrid_concepts",
            "hybrid_full",
        }
        for run in payload["runs"]:
            assert "metrics" in run
            assert "passed" in run

    def test_baseline_diff_round_trip(
        self, connection, fixture_vault: Path, settings: Settings, tmp_path: Path
    ) -> None:
        ingest_vault(connection, fixture_vault, settings)
        payload = evaluate_retrieval(connection, settings, builtin="fixture", top_k=5)
        baseline_file = tmp_path / "baseline.json"
        baseline_file.write_text(json.dumps(payload), encoding="utf-8")
        # Re-running against itself must show no regression.
        baseline_payload = json.loads(baseline_file.read_text(encoding="utf-8"))
        diff = diff_against_baseline(payload, baseline_payload)
        assert diff["regressed"] is False

    def test_existing_fixture_cases_still_passes_under_metrics(
        self, connection, fixture_vault: Path, settings: Settings
    ) -> None:
        # Backward-compat: evaluate_retrieval_cases still supports the
        # original case schema and still reports passed/failed counts.
        ingest_vault(connection, fixture_vault, settings)
        cases = [
            {
                "id": "north-star",
                "query": "North Star launch",
                "expected_paths": ["project-note.md"],
                "expected_terms": ["launch"],
            }
        ]
        payload = evaluate_retrieval_cases(connection, settings, cases, top_k=3)
        assert payload["passed"] == 1
        assert payload["metrics"]["hit_at_k"] == 1.0
