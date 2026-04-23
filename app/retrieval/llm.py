from __future__ import annotations

import json
from pathlib import Path
from urllib import error, request
from urllib.parse import urlparse

from app.config import Settings


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
            f"container itself. Set OLLAMA_BASE_URL to a host-reachable address such as "
            f"http://host.docker.internal:11434/api."
        )
    return detail


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


def _generate_text(prompt: str, settings: Settings, system_instruction: str) -> str:
    provider = settings.llm_provider.strip().lower()
    model_name = settings.get_synthesis_model_name(provider)
    if provider == "openai":
        if not settings.openai_api_key:
            raise LLMConfigurationError("OPENAI_API_KEY is not configured.")
        if not model_name:
            raise LLMConfigurationError("SYNTHESIS_MODEL_NAME is not configured.")
        payload = {
            "model": model_name,
            "instructions": system_instruction,
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
    if provider == "gemini":
        if not settings.gemini_api_key:
            raise LLMConfigurationError("GEMINI_API_KEY is not configured.")
        if not model_name:
            raise LLMConfigurationError("SYNTHESIS_MODEL_NAME is not configured.")
        payload = {"contents": [{"parts": [{"text": f"{system_instruction}\n\n{prompt}"}]}]}
        result = _post_json(
            f"{settings.gemini_base_url.rstrip('/')}/models/{model_name}:generateContent",
            {
                "x-goog-api-key": settings.gemini_api_key,
                "Content-Type": "application/json",
            },
            payload,
        )
        return _extract_gemini_text(result)
    if provider == "nvidia":
        if not settings.nvidia_api_key:
            raise LLMConfigurationError("NVIDIA_API_KEY is not configured.")
        if not model_name:
            raise LLMConfigurationError("SYNTHESIS_MODEL_NAME is not configured.")
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        }
        result = _post_json(
            settings.nvidia_base_url.rstrip("/") + "/chat/completions",
            {
                "Authorization": f"Bearer {settings.nvidia_api_key}",
                "Content-Type": "application/json",
            },
            payload,
        )
        return _extract_chat_completions_text(result, provider_name="NVIDIA")
    if provider == "ollama":
        if not model_name:
            raise LLMConfigurationError("SYNTHESIS_MODEL_NAME is not configured.")
        payload = {
            "model": model_name,
            "prompt": prompt,
            "system": system_instruction,
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
    raise LLMConfigurationError(f"Unsupported LLM_PROVIDER: {settings.llm_provider}")


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


def synthesize_answer(question: str, sources: list[dict[str, object]], settings: Settings) -> str:
    prompt = _build_prompt(question, sources)
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
