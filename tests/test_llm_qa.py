from __future__ import annotations

from urllib import error

from app.ingest.register import ingest_vault
from app.retrieval import llm, qa


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


def test_nvidia_chat_completions_parser_handles_string_content() -> None:
    result = {
        "choices": [
            {
                "message": {
                    "content": "Grounded answer [Source 1]",
                }
            }
        ]
    }

    assert llm._extract_chat_completions_text(result, provider_name="NVIDIA") == "Grounded answer [Source 1]"


def test_post_json_explains_localhost_misconfiguration_in_container(monkeypatch) -> None:
    def fake_urlopen(req, timeout=60):
        raise error.URLError(ConnectionRefusedError(111, "Connection refused"))

    monkeypatch.setattr(llm.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(llm, "_running_in_container", lambda: True)

    try:
        llm._post_json(
            "http://localhost:11434/api/generate",
            {"Content-Type": "application/json"},
            {"prompt": "test"},
        )
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected RuntimeError")

    assert "host.docker.internal" in message
    assert "localhost points to the container itself" in message
