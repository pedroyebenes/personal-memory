"""Deterministic concept/entity extraction from parsed documents and chunks.

Sources are intentionally local-only and do not require any LLM:

- ``wikilink`` — Obsidian-style ``[[Target]]`` / ``[[Target|Display]]`` references found in chunk text.
- ``tag``     — frontmatter ``tags`` entries.
- ``alias``   — frontmatter ``aliases`` entries; tied to the document's title concept.
- ``heading`` — section titles emitted by the chunker.
- ``title``   — the document title (frontmatter or inferred).
- ``filename``— normalized filename stem.

Document-scoped sources (``tag``, ``alias``, ``title``, ``filename``) are anchored to the
first chunk of the document. Chunk-scoped sources (``wikilink``, ``heading``) are anchored
to the chunk where they appear.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.models import ChunkRecord, ParsedDocument

WIKILINK_PATTERN = re.compile(r"\[\[([^\[\]\|]+)(?:\|([^\[\]]+))?\]\]")
_WHITESPACE = re.compile(r"\s+")
_STRUCTURAL_LABEL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\d+$"),
    re.compile(r"^[ivxlcdm]+$"),
    re.compile(r"^\d{4}\s+\d{1,2}\s+\d{1,2}$"),
    re.compile(r"^.+\.(?:md|txt|html|xhtml|xml)$"),
    re.compile(
        r"^(?:cap[ií]tulo|chapter|part|parte|book|libro|section|secci[oó]n)\s+"
        r"(?:[ivxlcdm]+|\d+|primero|segundo|tercero|cuarto|quinto|sexto|s[eé]ptimo|octavo|noveno|d[eé]cimo)$"
    ),
)
_STRUCTURAL_METHODS = {"heading", "title", "filename"}


EXTRACTION_METHODS: tuple[str, ...] = (
    "wikilink",
    "tag",
    "alias",
    "heading",
    "title",
    "filename",
)


@dataclass(slots=True)
class ConceptMention:
    canonical_name: str
    normalized_key: str
    entity_type: str
    mention_text: str
    extraction_method: str
    chunk_index: int


def normalize_key(value: str) -> str:
    cleaned = value.replace("_", " ").replace("-", " ")
    cleaned = _WHITESPACE.sub(" ", cleaned).strip().lower()
    return cleaned


def classify_entity_type(value: str, method: str) -> str:
    if method not in _STRUCTURAL_METHODS:
        return "concept"
    key = normalize_key(value)
    if any(pattern.match(key) for pattern in _STRUCTURAL_LABEL_PATTERNS):
        return "structure"
    return "concept"


def _make_mention(name: str, mention_text: str, method: str, chunk_index: int) -> ConceptMention | None:
    canonical = name.strip()
    if not canonical:
        return None
    key = normalize_key(canonical)
    if not key:
        return None
    return ConceptMention(
        canonical_name=canonical,
        normalized_key=key,
        entity_type=classify_entity_type(canonical, method),
        mention_text=mention_text.strip() or canonical,
        extraction_method=method,
        chunk_index=chunk_index,
    )


def _filename_concept(path: Path) -> str:
    stem = path.stem.replace("_", " ").replace("-", " ").strip()
    return stem


def _extract_wikilinks(chunks: list[ChunkRecord]) -> list[ConceptMention]:
    mentions: list[ConceptMention] = []
    for index, chunk in enumerate(chunks):
        for match in WIKILINK_PATTERN.finditer(chunk.text):
            target = match.group(1)
            display = match.group(2) or match.group(1)
            mention = _make_mention(target, display, "wikilink", index)
            if mention:
                mentions.append(mention)
    return mentions


def _extract_headings(chunks: list[ChunkRecord]) -> list[ConceptMention]:
    mentions: list[ConceptMention] = []
    for index, chunk in enumerate(chunks):
        if not chunk.section_title:
            continue
        mention = _make_mention(chunk.section_title, chunk.section_title, "heading", index)
        if mention:
            mentions.append(mention)
    return mentions


def extract_concept_mentions(parsed: ParsedDocument, chunks: list[ChunkRecord]) -> list[ConceptMention]:
    if not chunks:
        return []
    first_chunk_index = 0
    mentions: list[ConceptMention] = []

    title_mention = _make_mention(parsed.title, parsed.title, "title", first_chunk_index)
    if title_mention:
        mentions.append(title_mention)

    filename = _filename_concept(parsed.source_path)
    if filename and normalize_key(filename) != (title_mention.normalized_key if title_mention else None):
        filename_mention = _make_mention(filename, parsed.source_path.name, "filename", first_chunk_index)
        if filename_mention:
            mentions.append(filename_mention)

    for tag in parsed.tags:
        mention = _make_mention(tag, tag, "tag", first_chunk_index)
        if mention:
            mentions.append(mention)

    title_key = title_mention.normalized_key if title_mention else None
    title_canonical = title_mention.canonical_name if title_mention else parsed.title
    for alias in parsed.aliases:
        alias_key = normalize_key(alias)
        if not alias_key:
            continue
        canonical = title_canonical if title_key else alias
        mentions.append(
            ConceptMention(
                canonical_name=canonical,
                normalized_key=title_key or alias_key,
                entity_type=title_mention.entity_type if title_mention else "concept",
                mention_text=alias,
                extraction_method="alias",
                chunk_index=first_chunk_index,
            )
        )

    mentions.extend(_extract_wikilinks(chunks))
    mentions.extend(_extract_headings(chunks))
    return mentions
