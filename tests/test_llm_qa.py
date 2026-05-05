from __future__ import annotations

from urllib import error

from app.ingest.register import ingest_vault
from app.models import RetrievalResult
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

    def fake_synthesize_answer(question, sources, local_settings, conversation_history=None):
        assert question
        assert sources
        assert conversation_history == []
        assert local_settings.synthesis_model_name == "gemma3"
        assert local_settings.llm_provider == "ollama"
        return "Grounded answer [Source 1]"

    monkeypatch.setattr(qa, "synthesize_answer", fake_synthesize_answer)
    response = qa.answer_question(connection, "What is North Star?", settings, top_k=2, use_llm=True)
    assert response["answer_mode"] == "llm_synthesis"
    assert response["answer"] == "Grounded answer [Source 1]"
    assert response["provider"] == "ollama"
    assert "document_id" in response["sources"][0]


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


def test_synthesis_prompt_includes_history_and_expanded_context(settings, monkeypatch) -> None:
    captured = {}

    def fake_generate_text(prompt, local_settings, system_instruction):
        captured["prompt"] = prompt
        return "Grounded follow-up [Source 1]"

    monkeypatch.setattr(llm, "_generate_text", fake_generate_text)

    answer = llm.synthesize_answer(
        "What about that chunk?",
        [
            {
                "document_title": "Project Atlas",
                "source_path": "/tmp/atlas.md",
                "section_title": "Decision",
                "chunk_id": "7",
                "snippet": "The chunk says the cache is local.",
                "context": "Matched chunk 2\nSection: Decision\nThe broader note explains the cache tradeoff.",
            }
        ],
        settings,
        conversation_history=[
            {
                "question": "What did I decide about caching?",
                "answer": "You chose a local cache [Source 1].",
                "sources": [{"document_title": "Project Atlas", "source_path": "/tmp/atlas.md"}],
            }
        ],
    )

    assert answer == "Grounded follow-up [Source 1]"
    assert "Conversation context:" in captured["prompt"]
    assert "What did I decide about caching?" in captured["prompt"]
    assert "Expanded context:" in captured["prompt"]
    assert "The broader note explains the cache tradeoff." in captured["prompt"]
    assert "resolve references like that chunk" in captured["prompt"]


def test_answer_question_uses_history_for_retrieval_query(connection, settings, monkeypatch) -> None:
    captured = {}

    def fake_hybrid_search(local_connection, query, local_settings, **kwargs):
        captured["query"] = query
        return []

    monkeypatch.setattr(qa, "resolve_retrieval_query", lambda *args, **kwargs: ("that chunk", []))
    monkeypatch.setattr(qa, "hybrid_search", fake_hybrid_search)

    response = qa.answer_question(
        connection,
        "What about that chunk?",
        settings,
        conversation_history=[
            {
                "question": "Tell me about Project Atlas",
                "sources": [
                    {
                        "document_title": "Atlas Note",
                        "section_title": "Decision",
                        "source_path": "/vault/atlas.md",
                    }
                ],
            }
        ],
    )

    assert "that chunk" in captured["query"]
    assert "Previous question: Tell me about Project Atlas" in captured["query"]
    assert "Previous source: Atlas Note Decision /vault/atlas.md" in captured["query"]
    assert response["retrieval_query"] == captured["query"]


def test_answer_question_expands_source_context_for_llm(connection, fixture_vault, settings, monkeypatch) -> None:
    ingest_vault(connection, fixture_vault, settings)
    row = connection.execute(
        """
        SELECT c.id AS chunk_id, c.document_id, c.chunk_index, c.section_title, c.text,
               d.title AS document_title, d.source_path
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        ORDER BY c.id
        LIMIT 1
        """
    ).fetchone()
    result = RetrievalResult(
        document_title=str(row["document_title"]),
        source_path=str(row["source_path"]),
        chunk_id=int(row["chunk_id"]),
        chunk_index=int(row["chunk_index"]),
        section_title=row["section_title"],
        snippet=str(row["text"])[:120],
        keyword_score=1.0,
        semantic_score=None,
        final_score=1.0,
        document_id=int(row["document_id"]),
    )
    captured = {}

    def fake_hybrid_search(*args, **kwargs):
        return [result]

    def fake_synthesize_answer(question, sources, local_settings, conversation_history=None):
        captured["sources"] = sources
        captured["history"] = conversation_history
        return "Grounded answer with context [Source 1]"

    monkeypatch.setattr(qa, "hybrid_search", fake_hybrid_search)
    monkeypatch.setattr(qa, "synthesize_answer", fake_synthesize_answer)

    response = qa.answer_question(
        connection,
        "What more does that note say?",
        settings,
        use_llm=True,
        conversation_history=[{"question": "What is the note about?"}],
    )

    assert response["answer_mode"] == "llm_synthesis"
    assert captured["history"] == [{"question": "What is the note about?"}]
    assert captured["sources"][0]["document_id"] == int(row["document_id"])
    assert "Matched chunk" in captured["sources"][0]["context"]
    assert str(row["text"])[:80] in captured["sources"][0]["context"]
    assert "context" not in response["sources"][0]


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
