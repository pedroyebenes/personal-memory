from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.ingest.register import ingest_vault
from app.retrieval.evaluation import evaluate_retrieval_cases
from app.retrieval.hybrid_search import hybrid_search


def test_hybrid_search_exposes_exact_concept_boost_when_enabled(
    connection, tmp_path: Path, settings: Settings
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text(
        "---\ntitle: Note\n---\n\n# Section\n\nSee [[ExactBoostEntity]] for details.\n",
        encoding="utf-8",
    )
    ingest_vault(connection, vault, settings)

    results = hybrid_search(
        connection,
        "ExactBoostEntity",
        settings,
        top_k=5,
        use_concept_boost=True,
    )
    assert results
    top = results[0]
    assert top.score_explanation is not None
    assert "exact_concept_boost" in top.score_explanation
    assert float(top.score_explanation["exact_concept_boost"]) > 0
    assert top.score_explanation.get("exact_concept_matches")
    boosted = float(top.score_explanation["exact_concept_boost"])
    assert boosted <= 0.15


def test_hybrid_search_exact_boost_is_capped(connection, tmp_path: Path, settings: Settings) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    body = "# X\n\n" + " ".join(f"[[CapEntity{i}]]" for i in range(5))
    (vault / "many.md").write_text(
        f"---\ntitle: Many\n---\n\n{body}\n",
        encoding="utf-8",
    )
    ingest_vault(connection, vault, settings)

    results = hybrid_search(
        connection,
        "CapEntity0 CapEntity1 CapEntity2",
        settings,
        top_k=3,
        use_concept_boost=True,
    )
    assert results
    for r in results:
        ex = r.score_explanation or {}
        if float(ex.get("exact_concept_boost") or 0) > 0:
            assert float(ex["exact_concept_boost"]) <= 0.15


def test_hybrid_search_debug_scores_adds_fusion_weights(
    connection, fixture_vault: Path, settings: Settings
) -> None:
    ingest_vault(connection, fixture_vault, settings)
    results = hybrid_search(
        connection,
        "weekly review",
        settings,
        top_k=3,
        debug_scores=True,
    )
    assert results
    assert results[0].score_explanation
    assert "fusion_weights" in results[0].score_explanation


def test_retrieval_eval_fixture_cases_still_pass(connection, fixture_vault: Path, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)
    cases = [
        {
            "id": "north-star",
            "query": "North Star launch",
            "expected_paths": ["project-note.md"],
            "expected_terms": ["launch"],
        },
        {
            "id": "weekly",
            "query": "weekly review",
            "expected_paths": [],
            "expected_terms": ["review"],
        },
    ]
    payload = evaluate_retrieval_cases(connection, settings, cases, top_k=3)
    assert payload["status"] == "passed"
    assert payload["passed"] == 2
