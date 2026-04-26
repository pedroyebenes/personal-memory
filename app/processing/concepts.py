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
INLINE_TAG_PATTERN = re.compile(r"(?<![\w/])#([A-Za-z][A-Za-z0-9_/-]{1,80})")
EMPHASIS_PATTERN = re.compile(r"(?<!\*)\*\*([^*\n]{3,120})\*\*(?!\*)|(?<!\w)_([^_\n]{3,120})_(?!\w)")
DEFINITION_PATTERN = re.compile(
    r"(?m)^\s*(?:[-*]\s+)?([A-ZÁÉÍÓÚÜÑ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9'’/-]*(?:[ \t]+[A-ZÁÉÍÓÚÜÑ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9'’/-]*){0,5})[ \t]+"
    r"(?:is|means|refers to|describes|es|significa|se refiere a|describe)[ \t]+.{8,}"
)
COLON_DEFINITION_PATTERN = re.compile(
    r"(?m)^\s*(?:[-*]\s+)?([A-ZÁÉÍÓÚÜÑ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9'’/-]*(?:[ \t]+[A-ZÁÉÍÓÚÜÑ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9'’/-]*){0,5})[ \t]*:[ \t]+.{8,}"
)
CAPITALIZED_PHRASE_PATTERN = re.compile(
    r"\b([A-ZÁÉÍÓÚÜÑ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9'’/-]*(?:[ \t]+[A-ZÁÉÍÓÚÜÑ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9'’/-]*){1,5})\b"
)
_WHITESPACE = re.compile(r"\s+")
_MARKDOWN_LINK_PATTERN = re.compile(r"!?\[[^\]]+\]\([^)]+\)")
_CODE_SPAN_PATTERN = re.compile(r"`[^`]+`")
_MAX_BODY_MENTIONS_PER_CHUNK = 24
_BODY_MIN_OCCURRENCES = 2
_BODY_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "the",
    "this",
    "to",
    "with",
}
_BODY_STOP_PHRASES = {
    "table of contents",
    "copyright",
    "all rights reserved",
    "public domain",
}

_MONTH_NAMES_EN_ES = (
    "january|february|march|april|may|june|july|august|september|october|november|december|"
    "enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre"
)
_WEEKDAY_NAMES_EN_ES = (
    "monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    "lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo"
)

_STRUCTURAL_LABEL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\d+$"),
    re.compile(r"^[ivxlcdm]+$"),
    re.compile(r"^\d{4}\s+\d{1,2}\s+\d{1,2}$"),
    re.compile(r"^.+\.(?:md|txt|html|xhtml|xml)$"),
    re.compile(
        r"^(?:cap[ií]tulo|chapter|part|parte|book|libro|section|secci[oó]n)\s+"
        r"(?:[ivxlcdm]+|\d+|primero|segundo|tercero|cuarto|quinto|sexto|s[eé]ptimo|octavo|noveno|d[eé]cimo)"
        r"(?:\b|[.:])"
    ),
    re.compile(
        r"^(?:cap[ií]tulo|chapter|part|parte|book|libro|section|secci[oó]n)\s+"
        r"(?:[ivxlcdm]+|\d+|primero|segundo|tercero|cuarto|quinto|sexto|s[eé]ptimo|octavo|noveno|d[eé]cimo)$"
    ),
    # Subtitled chapter/section: "Capítulo IV: …", "Chapter 3 — …"
    re.compile(
        r"^(?:cap[ií]tulo|chapter|part|parte|book|libro|section|secci[oó]n|tomo)\s+"
        r"\S+(?:\s*[:—–-]\s+.+)?$"
    ),
    # Front matter / back matter headings
    re.compile(
        r"^(?:pr[oó]logo|ep[ií]logo|introducci[oó]n|pref[aá]cio|dedicatoria|[ií]ndice|"
        r"tabla\s+de\s+contenidos|glosario|ap[eé]ndice|nota\s+del\s+autor|acknowledgments?)\b"
    ),
    # Ordinals spelled out: "Parte Primera", "Libro Tercero"
    re.compile(
        r"^(?:parte|cap[ií]tulo|libro)\s+"
        r"(?:primero|primera|segundo|segunda|tercero|tercera|cuarto|cuarta|quinto|quinta|"
        r"sexto|sexta|s[eé]ptimo|s[eé]ptima|octavo|octava|noveno|novena|d[eé]cimo|d[eé]cima|"
        r"und[eé]cimo|und[eé]cima|duod[eé]cimo|duod[eé]cima)\b"
    ),
    re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    re.compile(r"^\d{4}/\d{2}/\d{2}$"),
    re.compile(
        rf"^(?:{_MONTH_NAMES_EN_ES})\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s*\d{{4}})?$"
    ),
    re.compile(rf"^\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{_MONTH_NAMES_EN_ES})(?:,?\s*\d{{4}})?$"),
    re.compile(rf"^(?:{_WEEKDAY_NAMES_EN_ES})$"),
)
STRUCTURAL_CLASSIFICATION_METHODS: frozenset[str] = frozenset({"heading", "title", "filename", "alias"})
_STRUCTURAL_METHODS = STRUCTURAL_CLASSIFICATION_METHODS


EXTRACTION_METHODS: tuple[str, ...] = (
    "wikilink",
    "tag",
    "alias",
    "heading",
    "title",
    "filename",
    "inline_tag",
    "emphasis",
    "definition",
    "body_phrase",
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


def entity_type_from_recorded_methods(canonical_name: str, methods: set[str]) -> str:
    """Pick entity_type for an existing row given its canonical label and mention methods."""
    structural = methods.intersection(STRUCTURAL_CLASSIFICATION_METHODS)
    if not structural:
        return "concept"
    for method in sorted(structural):
        if classify_entity_type(canonical_name, method) == "structure":
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


def _clean_body_label(value: str) -> str:
    cleaned = value.strip()
    cleaned = re.sub(r"^[#*_`~\s:;,.!?()\[\]{}<>\"'“”‘’]+", "", cleaned)
    cleaned = re.sub(r"[#*_`~\s:;,.!?()\[\]{}<>\"'“”‘’]+$", "", cleaned)
    return _WHITESPACE.sub(" ", cleaned).strip()


def _is_good_body_label(value: str) -> bool:
    cleaned = _clean_body_label(value)
    key = normalize_key(cleaned)
    if not key or key in _BODY_STOP_PHRASES:
        return False
    words = key.split()
    if len(words) > 6:
        return False
    if len(words) == 1 and (len(words[0]) < 3 or words[0] in _BODY_STOPWORDS):
        return False
    if all(word in _BODY_STOPWORDS for word in words):
        return False
    if not any(char.isalpha() for char in cleaned):
        return False
    if classify_entity_type(cleaned, "heading") == "structure":
        return False
    return True


def _strip_markup_for_body_phrases(text: str) -> str:
    without_links = _MARKDOWN_LINK_PATTERN.sub(" ", text)
    without_code = _CODE_SPAN_PATTERN.sub(" ", without_links)
    return WIKILINK_PATTERN.sub(" ", without_code)


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


def _extract_inline_tags(chunks: list[ChunkRecord]) -> list[ConceptMention]:
    mentions: list[ConceptMention] = []
    for index, chunk in enumerate(chunks):
        for match in INLINE_TAG_PATTERN.finditer(chunk.text):
            label = match.group(1).replace("/", " ")
            mention = _make_mention(label, f"#{match.group(1)}", "inline_tag", index)
            if mention:
                mentions.append(mention)
    return mentions


def _extract_emphasis(chunks: list[ChunkRecord]) -> list[ConceptMention]:
    mentions: list[ConceptMention] = []
    for index, chunk in enumerate(chunks):
        for match in EMPHASIS_PATTERN.finditer(chunk.text):
            label = _clean_body_label(match.group(1) or match.group(2) or "")
            if not _is_good_body_label(label):
                continue
            mention = _make_mention(label, label, "emphasis", index)
            if mention:
                mentions.append(mention)
    return mentions


def _extract_definitions(chunks: list[ChunkRecord]) -> list[ConceptMention]:
    mentions: list[ConceptMention] = []
    for index, chunk in enumerate(chunks):
        for pattern in (DEFINITION_PATTERN, COLON_DEFINITION_PATTERN):
            for match in pattern.finditer(chunk.text):
                label = _clean_body_label(match.group(1))
                if not _is_good_body_label(label):
                    continue
                mention = _make_mention(label, label, "definition", index)
                if mention:
                    mentions.append(mention)
    return mentions


def _extract_body_phrases(chunks: list[ChunkRecord]) -> list[ConceptMention]:
    candidates: dict[str, dict[str, object]] = {}
    for index, chunk in enumerate(chunks):
        seen_in_chunk: set[str] = set()
        text = _strip_markup_for_body_phrases(chunk.text)
        for match in CAPITALIZED_PHRASE_PATTERN.finditer(text):
            label = _clean_body_label(match.group(1))
            if not _is_good_body_label(label):
                continue
            key = normalize_key(label)
            bucket = candidates.setdefault(
                key,
                {"canonical": label, "occurrences": 0, "chunk_indexes": set()},
            )
            bucket["occurrences"] = int(bucket["occurrences"]) + 1
            if key not in seen_in_chunk:
                bucket["chunk_indexes"].add(index)
                seen_in_chunk.add(key)

    mentions: list[ConceptMention] = []
    per_chunk_counts: dict[int, int] = {}
    for key in sorted(candidates):
        bucket = candidates[key]
        if int(bucket["occurrences"]) < _BODY_MIN_OCCURRENCES:
            continue
        canonical = str(bucket["canonical"])
        for chunk_index in sorted(bucket["chunk_indexes"]):
            if per_chunk_counts.get(chunk_index, 0) >= _MAX_BODY_MENTIONS_PER_CHUNK:
                continue
            mention = _make_mention(canonical, canonical, "body_phrase", chunk_index)
            if mention:
                mentions.append(mention)
                per_chunk_counts[chunk_index] = per_chunk_counts.get(chunk_index, 0) + 1
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
        if classify_entity_type(alias, "alias") == "structure":
            structural_alias = _make_mention(alias, alias, "alias", first_chunk_index)
            if structural_alias:
                mentions.append(structural_alias)
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
    mentions.extend(_extract_inline_tags(chunks))
    mentions.extend(_extract_emphasis(chunks))
    mentions.extend(_extract_definitions(chunks))
    mentions.extend(_extract_body_phrases(chunks))
    return mentions
