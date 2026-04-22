from __future__ import annotations

import sqlite3

from app.config import Settings
from app.retrieval.hybrid_search import hybrid_search


def answer_question(connection: sqlite3.Connection, query: str, settings: Settings, top_k: int = 5) -> dict[str, object]:
    results = hybrid_search(connection, query, settings, top_k=top_k)
    if not results:
        return {"question": query, "answer": "No relevant evidence found.", "sources": []}

    evidence_lines = []
    sources = []
    for result in results:
        section = f" [{result.section_title}]" if result.section_title else ""
        evidence_lines.append(f"- {result.document_title}{section}: {result.snippet}")
        sources.append(
            {
                "document_title": result.document_title,
                "source_path": result.source_path,
                "chunk_id": str(result.chunk_id),
                "chunk_index": result.chunk_index,
                "section_title": result.section_title,
                "snippet": result.snippet,
            }
        )

    answer = "Relevant evidence:\n" + "\n".join(evidence_lines)
    return {"question": query, "answer": answer, "sources": sources}
