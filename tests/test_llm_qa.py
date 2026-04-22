from __future__ import annotations

from app.ingest.register import ingest_vault
from app.retrieval import qa


def test_answer_question_falls_back_when_llm_unconfigured(connection, fixture_vault, settings) -> None:
    ingest_vault(connection, fixture_vault, settings)
    response = qa.answer_question(connection, "What is North Star?", settings, top_k=2, use_llm=True)
    assert response["answer_mode"] == "extractive"
    assert response["warnings"]


def test_answer_question_uses_llm_when_available(connection, fixture_vault, settings, monkeypatch) -> None:
    ingest_vault(connection, fixture_vault, settings)
    settings.llm_provider = "ollama"
    settings.enable_llm_synthesis = True
    settings.synthesis_model_name = "gemma3"

    def fake_synthesize_answer(question, sources, local_settings):
        assert question
        assert sources
        assert local_settings.synthesis_model_name == "gemma3"
        assert local_settings.llm_provider == "ollama"
        return "Grounded answer [Source 1]"

    monkeypatch.setattr(qa, "synthesize_answer", fake_synthesize_answer)
    response = qa.answer_question(connection, "What is North Star?", settings, top_k=2, use_llm=True)
    assert response["answer_mode"] == "llm_synthesis"
    assert response["answer"] == "Grounded answer [Source 1]"
    assert response["provider"] == "ollama"
