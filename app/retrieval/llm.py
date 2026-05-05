from __future__ import annotations

import json
from pathlib import Path
from urllib import error, request
from urllib.parse import urlparse

from app.config import Settings, normalize_provider_name


class LLMConfigurationError(RuntimeError):
    """Raised when LLM synthesis is requested without usable configuration."""


def _running_in_container() -> bool:
    return Path("/.dockerenv").exists()


def _is_localhost_url(url: str) -> bool:
    hostname = (urlparse(url).hostname or "").strip().lower()
    return hostname in {"localhost", "127.0.0.1", "::1"}


def _augment_connection_error(url: str, reason: object) -> str:
    detail = str(reason)
    if _running_in_container() and _is_localhost_url(url):
        return (
            f"{detail}. The app appears to be running in a container, where localhost points to the "
            f"container itself. Set the selected provider's base URL to a host-reachable address, "
            f"for example http://host.docker.internal:11434/api for Ollama."
        )
    return detail


def _format_sources(sources: list[dict[str, object]]) -> str:
    blocks: list[str] = []
    for index, source in enumerate(sources, start=1):
        section_title = source.get("section_title") or "No section title"
        lines = [
            f"[Source {index}]",
            f"Document: {source['document_title']}",
            f"Path: {source['source_path']}",
            f"Section: {section_title}",
            f"Chunk ID: {source['chunk_id']}",
            f"Snippet: {source['snippet']}",
        ]
        context = source.get("context")
        if isinstance(context, str) and context.strip():
            lines.extend(["Expanded context:", context.strip()])
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _compact_text(value: object, limit: int = 500) -> str:
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _format_conversation_history(history: list[dict[str, object]] | None) -> str:
    if not isinstance(history, list):
        return ""
    blocks: list[str] = []
    for index, turn in enumerate(history[-6:], start=1):
        if not isinstance(turn, dict):
            continue
        question = _compact_text(turn.get("question"), limit=300)
        answer = _compact_text(turn.get("answer"), limit=500)
        lines = [f"[Turn {index}]"]
        if question:
            lines.append(f"Question: {question}")
        if answer:
            lines.append(f"Answer: {answer}")
        sources = turn.get("sources", [])
        if isinstance(sources, list):
            labels = []
            for source in sources[:3]:
                if not isinstance(source, dict):
                    continue
                title = _compact_text(source.get("document_title"), limit=120)
                section = _compact_text(source.get("section_title"), limit=120)
                path = _compact_text(source.get("source_path"), limit=180)
                label = " / ".join(part for part in (title, section, path) if part)
                if label:
                    labels.append(label)
            if labels:
                lines.append("Sources: " + "; ".join(labels))
        if len(lines) > 1:
            blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _build_prompt(
    question: str,
    sources: list[dict[str, object]],
    conversation_history: list[dict[str, object]] | None = None,
) -> str:
    history = _format_conversation_history(conversation_history)
    history_block = f"Conversation context:\n{history}\n\n" if history else ""
    return (
        "Answer the user's question using only the provided sources.\n"
        "Rules:\n"
        "- Do not introduce facts that are not in the sources.\n"
        "- If the evidence is insufficient, say so plainly.\n"
        "- Cite supporting claims inline using [Source N].\n"
        "- For follow-up questions, use conversation context to resolve references like that chunk, the note, or it.\n"
        "- Use conversation context only for reference resolution; factual claims must be supported by the sources.\n"
        "- Answer in the primary language of the evidence snippets, even if the question uses another language.\n"
        "- If sources use multiple languages, use the language of the most relevant evidence.\n"
        "- Keep the answer concise and readable.\n\n"
        f"{history_block}"
        f"Question:\n{question}\n\n"
        f"Sources:\n{_format_sources(sources)}"
    )


def _call_openai(prompt: str, system_instruction: str, settings: Settings, model_name: str | None) -> str:
    if not settings.openai_api_key:
        raise LLMConfigurationError("OPENAI_API_KEY is not configured.")
    if not model_name:
        raise LLMConfigurationError("SYNTHESIS_MODEL_NAME is not configured.")
    payload = {"model": model_name, "instructions": system_instruction, "input": prompt}
    result = _post_json(
        settings.openai_base_url.rstrip("/") + "/responses",
        {"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"},
        payload,
    )
    return _extract_openai_text(result)


def _call_gemini(prompt: str, system_instruction: str, settings: Settings, model_name: str | None) -> str:
    if not settings.gemini_api_key:
        raise LLMConfigurationError("GEMINI_API_KEY is not configured.")
    if not model_name:
        raise LLMConfigurationError("SYNTHESIS_MODEL_NAME is not configured.")
    payload = {"contents": [{"parts": [{"text": f"{system_instruction}\n\n{prompt}"}]}]}
    result = _post_json(
        f"{settings.gemini_base_url.rstrip('/')}/models/{model_name}:generateContent",
        {"x-goog-api-key": settings.gemini_api_key, "Content-Type": "application/json"},
        payload,
    )
    return _extract_gemini_text(result)


def _call_nvidia(prompt: str, system_instruction: str, settings: Settings, model_name: str | None) -> str:
    if not settings.nvidia_api_key:
        raise LLMConfigurationError("NVIDIA_API_KEY is not configured.")
    if not model_name:
        raise LLMConfigurationError("SYNTHESIS_MODEL_NAME is not configured.")
    payload = {
        "model": model_name,
        "messages": [{"role": "system", "content": system_instruction}, {"role": "user", "content": prompt}],
        "stream": False,
    }
    result = _post_json(
        settings.nvidia_base_url.rstrip("/") + "/chat/completions",
        {"Authorization": f"Bearer {settings.nvidia_api_key}", "Content-Type": "application/json"},
        payload,
    )
    return _extract_chat_completions_text(result, provider_name="NVIDIA")


def _call_mlx_lm(prompt: str, system_instruction: str, settings: Settings, model_name: str | None) -> str:
    payload: dict[str, object] = {
        "messages": [{"role": "system", "content": system_instruction}, {"role": "user", "content": prompt}],
        "stream": False,
    }
    if model_name:
        payload["model"] = model_name
    result = _post_json(
        settings.mlx_lm_base_url.rstrip("/") + "/chat/completions",
        {"Content-Type": "application/json"},
        payload,
    )
    return _extract_chat_completions_text(result, provider_name="MLX-LM")


def _call_ollama(prompt: str, system_instruction: str, settings: Settings, model_name: str | None) -> str:
    if not model_name:
        raise LLMConfigurationError("SYNTHESIS_MODEL_NAME is not configured.")
    payload = {"model": model_name, "prompt": prompt, "system": system_instruction, "stream": False}
    result = _post_json(
        settings.ollama_base_url.rstrip("/") + "/generate",
        {"Content-Type": "application/json"},
        payload,
    )
    response_text = result.get("response")
    if isinstance(response_text, str) and response_text.strip():
        return response_text.strip()
    raise RuntimeError("Ollama response did not contain text output.")


_PROVIDER_HANDLERS: dict[str, object] = {
    "openai": _call_openai,
    "gemini": _call_gemini,
    "nvidia": _call_nvidia,
    "mlx_lm": _call_mlx_lm,
    "ollama": _call_ollama,
}


def _invoke_provider(provider: str, prompt: str, system_instruction: str, settings: Settings) -> str:
    handler = _PROVIDER_HANDLERS.get(provider)
    if handler is None:
        raise LLMConfigurationError(f"Unsupported LLM_PROVIDER: {provider!r}")
    model_name = settings.get_synthesis_model_name(provider)
    return handler(prompt, system_instruction, settings, model_name)  # type: ignore[operator]


def _generate_text(prompt: str, settings: Settings, system_instruction: str) -> str:
    provider = normalize_provider_name(settings.llm_provider)
    try:
        return _invoke_provider(provider, prompt, system_instruction, settings)
    except LLMConfigurationError:
        fallback = normalize_provider_name(settings.fallback_llm_provider)
        if fallback and fallback != provider and fallback in _PROVIDER_HANDLERS:
            return _invoke_provider(fallback, prompt, system_instruction, settings)
        raise


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
        raise RuntimeError(f"LLM request failed: {_augment_connection_error(url, exc.reason)}") from exc
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


def _extract_chat_completions_text(result: dict[str, object], provider_name: str) -> str:
    choices = result.get("choices", [])
    if not isinstance(choices, list):
        raise RuntimeError(f"{provider_name} API response did not contain choices.")
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message", {})
        if isinstance(message, str) and message.strip():
            return message.strip()
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            texts = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text" and item.get("text"):
                    texts.append(str(item["text"]))
            if texts:
                return "\n".join(texts).strip()
    raise RuntimeError(f"{provider_name} API response did not contain text output.")


def synthesize_answer(
    question: str,
    sources: list[dict[str, object]],
    settings: Settings,
    conversation_history: list[dict[str, object]] | None = None,
) -> str:
    prompt = _build_prompt(question, sources, conversation_history=conversation_history)
    return _generate_text(
        prompt,
        settings,
        system_instruction="You are a citation-grounded assistant for a local personal memory system.",
    )


def rewrite_query(query: str, settings: Settings) -> str:
    prompt = (
        "Rewrite the user's question into a compact retrieval query for note search.\n"
        "Rules:\n"
        "- Keep the same intent.\n"
        "- Prefer key nouns, names, aliases, topics, and likely note terminology.\n"
        "- Output one line only.\n"
        "- Do not explain your reasoning.\n\n"
        f"Question:\n{query}"
    )
    result = _generate_text(
        prompt,
        settings,
        system_instruction="You rewrite natural-language questions into better retrieval queries for a local notes search engine.",
    )
    return " ".join(result.strip().splitlines()).strip()
