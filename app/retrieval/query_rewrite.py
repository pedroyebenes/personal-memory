from __future__ import annotations

from app.config import Settings
from app.retrieval.llm import LLMConfigurationError, rewrite_query


def resolve_retrieval_query(
    query: str,
    settings: Settings,
    use_query_rewrite: bool | None = None,
) -> tuple[str, list[str]]:
    should_rewrite = settings.enable_query_rewrite if use_query_rewrite is None else use_query_rewrite
    warnings: list[str] = []
    if not should_rewrite:
        return query, warnings
    try:
        rewritten = rewrite_query(query, settings)
    except LLMConfigurationError as exc:
        warnings.append(str(exc))
        return query, warnings
    except RuntimeError as exc:
        warnings.append(f"Query rewrite failed: {exc}")
        return query, warnings
    if not rewritten:
        warnings.append("Query rewrite returned empty output; original query used instead")
        return query, warnings
    return rewritten, warnings
