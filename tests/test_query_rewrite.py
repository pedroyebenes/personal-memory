from __future__ import annotations

from app.config import Settings
from app.retrieval.query_rewrite import resolve_retrieval_query


def test_query_rewrite_disabled_keeps_original_query(settings: Settings) -> None:
    query, warnings = resolve_retrieval_query("What did I decide about retrieval?", settings, use_query_rewrite=False)
    assert query == "What did I decide about retrieval?"
    assert warnings == []


def test_query_rewrite_falls_back_when_unconfigured(settings: Settings) -> None:
    settings.synthesis_model_name = ""
    settings.ollama_synthesis_model_name = ""

    query, warnings = resolve_retrieval_query("What did I decide about retrieval?", settings, use_query_rewrite=True)
    assert query == "What did I decide about retrieval?"
    assert warnings
