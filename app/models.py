from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ParsedDocument:
    source_path: Path
    title: str
    raw_text: str
    normalized_text: str
    frontmatter: dict[str, Any]
    tags: list[str]
    aliases: list[str]


@dataclass(slots=True)
class ChunkRecord:
    chunk_index: int
    section_title: str | None
    text: str
    token_estimate: int
    char_start: int
    char_end: int


@dataclass(slots=True)
class RetrievalResult:
    document_title: str
    source_path: str
    chunk_id: int
    chunk_index: int
    section_title: str | None
    snippet: str
    keyword_score: float | None
    semantic_score: float | None
    final_score: float
    metadata_score: float = 0.0
    rerank_score: float = 0.0
    score_explanation: dict[str, object] | None = None


@dataclass(slots=True)
class SearchFilters:
    tags: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    path_prefix: str | None = None
    date_from: str | None = None
    date_to: str | None = None
