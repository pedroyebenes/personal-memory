from __future__ import annotations

import json
from urllib import error, request

from app.config import Settings


class LLMConfigurationError(RuntimeError):
    """Raised when LLM synthesis is requested without usable configuration."""


def _format_sources(sources: list[dict[str, object]]) -> str:
    blocks: list[str] = []
    for index, source in enumerate(sources, start=1):
        section_title = source.get("section_title") or "No section title"
        blocks.append(
            "\n".join(
                [
                    f"[Source {index}]",
                    f"Document: {source['document_title']}",
                    f"Path: {source['source_path']}",
                    f"Section: {section_title}",
                    f"Chunk ID: {source['chunk_id']}",
                    f"Snippet: {source['snippet']}",
                ]
            )
        )
    return "\n\n".join(blocks)


def _build_prompt(question: str, sources: list[dict[str, object]]) -> str:
    return (
        "Answer the user's question using only the provided sources.\n"
        "Rules:\n"
        "- Do not introduce facts that are not in the sources.\n"
        "- If the evidence is insufficient, say so plainly.\n"
        "- Cite supporting claims inline using [Source N].\n"
        "- Keep the answer concise and readable.\n\n"
        f"Question:\n{question}\n\n"
        f"Sources:\n{_format_sources(sources)}"
    )


def _post_json(url: str, headers: dict[str, str], payload: dict[str, object]) -> dict[str, object]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM request failed with status {exc.code}: {message}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"LLM request failed: {exc.reason}") from exc
    if not isinstance(result, dict):
        raise RuntimeError("LLM response was not a JSON object.")
    return result


def _extract_openai_text(result: dict[str, object]) -> str:
    output_text = result.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    output = result.get("output", [])
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if isinstance(content, dict) and content.get("type") == "output_text" and content.get("text"):
                    return str(content["text"]).strip()
    raise RuntimeError("OpenAI API response did not contain text output.")


def _extract_gemini_text(result: dict[str, object]) -> str:
    candidates = result.get("candidates", [])
    if not isinstance(candidates, list):
        raise RuntimeError("Gemini API response did not contain candidates.")
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content", {})
        if not isinstance(content, dict):
            continue
        parts = content.get("parts", [])
        if not isinstance(parts, list):
            continue
        texts = [part.get("text", "") for part in parts if isinstance(part, dict) and part.get("text")]
        if texts:
            return "\n".join(texts).strip()
    raise RuntimeError("Gemini API response did not contain text output.")


def _synthesize_openai(prompt: str, settings: Settings) -> str:
    if not settings.openai_api_key:
        raise LLMConfigurationError("OPENAI_API_KEY is not configured.")
    if not settings.synthesis_model_name:
        raise LLMConfigurationError("SYNTHESIS_MODEL_NAME is not configured.")
    payload = {
        "model": settings.synthesis_model_name,
        "instructions": "You are a citation-grounded assistant for a local personal memory system.",
        "input": prompt,
    }
    result = _post_json(
        settings.openai_base_url.rstrip("/") + "/responses",
        {
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        payload,
    )
    return _extract_openai_text(result)


def _synthesize_gemini(prompt: str, settings: Settings) -> str:
    if not settings.gemini_api_key:
        raise LLMConfigurationError("GEMINI_API_KEY is not configured.")
    if not settings.synthesis_model_name:
        raise LLMConfigurationError("SYNTHESIS_MODEL_NAME is not configured.")
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt,
                    }
                ]
            }
        ]
    }
    result = _post_json(
        f"{settings.gemini_base_url.rstrip('/')}/models/{settings.synthesis_model_name}:generateContent",
        {
            "x-goog-api-key": settings.gemini_api_key,
            "Content-Type": "application/json",
        },
        payload,
    )
    return _extract_gemini_text(result)


def _synthesize_ollama(prompt: str, settings: Settings) -> str:
    if not settings.synthesis_model_name:
        raise LLMConfigurationError("SYNTHESIS_MODEL_NAME is not configured.")
    payload = {
        "model": settings.synthesis_model_name,
        "prompt": prompt,
        "system": "You are a citation-grounded assistant for a local personal memory system.",
        "stream": False,
    }
    result = _post_json(
        settings.ollama_base_url.rstrip("/") + "/generate",
        {"Content-Type": "application/json"},
        payload,
    )
    response_text = result.get("response")
    if isinstance(response_text, str) and response_text.strip():
        return response_text.strip()
    raise RuntimeError("Ollama response did not contain text output.")


def synthesize_answer(question: str, sources: list[dict[str, object]], settings: Settings) -> str:
    prompt = _build_prompt(question, sources)
    provider = settings.llm_provider.strip().lower()
    if provider == "openai":
        return _synthesize_openai(prompt, settings)
    if provider == "gemini":
        return _synthesize_gemini(prompt, settings)
    if provider == "ollama":
        return _synthesize_ollama(prompt, settings)
    raise LLMConfigurationError(f"Unsupported LLM_PROVIDER: {settings.llm_provider}")
