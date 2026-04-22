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


def synthesize_answer(question: str, sources: list[dict[str, object]], settings: Settings) -> str:
    if not settings.openai_api_key:
        raise LLMConfigurationError("OPENAI_API_KEY is not configured.")
    if not settings.synthesis_model_name:
        raise LLMConfigurationError("SYNTHESIS_MODEL_NAME is not configured.")

    prompt = (
        "Answer the user's question using only the provided sources.\n"
        "Rules:\n"
        "- Do not introduce facts that are not in the sources.\n"
        "- If the evidence is insufficient, say so plainly.\n"
        "- Cite supporting claims inline using [Source N].\n"
        "- Keep the answer concise and readable.\n\n"
        f"Question:\n{question}\n\n"
        f"Sources:\n{_format_sources(sources)}"
    )

    payload = {
        "model": settings.synthesis_model_name,
        "instructions": "You are a citation-grounded assistant for a local personal memory system.",
        "input": prompt,
    }
    body = json.dumps(payload).encode("utf-8")
    api_url = settings.openai_base_url.rstrip("/") + "/responses"
    req = request.Request(
        api_url,
        data=body,
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API request failed with status {exc.code}: {message}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"OpenAI API request failed: {exc.reason}") from exc

    output_text = result.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    output = result.get("output", [])
    for item in output:
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                return str(content["text"]).strip()
    raise RuntimeError("OpenAI API response did not contain text output.")
