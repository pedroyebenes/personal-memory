from __future__ import annotations

from urllib import error

from app.ingest.register import ingest_vault
from app.retrieval import llm, qa


def test_answer_question_falls_back_when_llm_unconfigured(connection, fixture_vault, settings) -> None:
    ingest_vault(connection, fixture_vault, settings)
    settings.synthesis_model_name = ""
    settings.ollama_synthesis_model_name = ""

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


def test_synthesis_prompt_asks_for_evidence_language(settings, monkeypatch) -> None:
    captured = {}

    def fake_generate_text(prompt, local_settings, system_instruction):
        captured["prompt"] = prompt
        captured["settings"] = local_settings
        captured["system_instruction"] = system_instruction
        return "Respuesta fundamentada [Source 1]"

    monkeypatch.setattr(llm, "_generate_text", fake_generate_text)

    answer = llm.synthesize_answer(
        "What did the note decide?",
        [
            {
                "document_title": "Nota",
                "source_path": "/tmp/nota.md",
                "section_title": "Resumen",
                "chunk_id": "1",
                "snippet": "La decisión fue responder en español.",
            }
        ],
        settings,
    )

    assert answer == "Respuesta fundamentada [Source 1]"
    assert "Answer in the primary language of the evidence snippets" in captured["prompt"]
    assert "If sources use multiple languages" in captured["prompt"]
    assert "La decisión fue responder en español." in captured["prompt"]


def test_answer_question_keeps_rewrite_warnings_when_no_results(connection, settings, monkeypatch) -> None:
    monkeypatch.setattr(qa, "resolve_retrieval_query", lambda *args, **kwargs: ("rewritten", ["rewrite failed"]))
    monkeypatch.setattr(qa, "hybrid_search", lambda *args, **kwargs: [])

    response = qa.answer_question(connection, "Missing topic", settings, use_query_rewrite=True)

    assert response["warnings"] == ["rewrite failed", "retrieval returned no evidence"]


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


def test_mlx_lm_chat_completions_parser_handles_string_message() -> None:
    result = {
        "choices": [
            {
                "message": "Grounded answer [Source 1]",
            }
        ]
    }

    assert llm._extract_chat_completions_text(result, provider_name="MLX-LM") == "Grounded answer [Source 1]"


def test_mlx_lm_generate_uses_chat_completions_without_required_model(settings, monkeypatch) -> None:
    settings.llm_provider = "mlx_lm"
    settings.synthesis_model_name = None
    settings.mlx_lm_synthesis_model_name = ""
    settings.mlx_lm_base_url = "http://localhost:8080/v1"
    captured = {}

    def fake_post_json(url, headers, payload):
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        return {"choices": [{"message": {"content": "Grounded answer [Source 1]"}}]}

    monkeypatch.setattr(llm, "_post_json", fake_post_json)

    answer = llm._generate_text("Question and sources", settings, "System instruction")

    assert answer == "Grounded answer [Source 1]"
    assert captured["url"] == "http://localhost:8080/v1/chat/completions"
    assert captured["headers"] == {"Content-Type": "application/json"}
    assert captured["payload"]["messages"] == [
        {"role": "system", "content": "System instruction"},
        {"role": "user", "content": "Question and sources"},
    ]
    assert "model" not in captured["payload"]


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
