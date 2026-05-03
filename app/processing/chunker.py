from __future__ import annotations

import re

from app.models import ChunkRecord

HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)


def breadcrumb_text(document_title: str, heading_path: list[str], chunk_text: str) -> str:
    """Text passed to the embedding model: title, heading trail, then raw chunk body."""
    doc = (document_title or "").strip() or "Untitled"
    body = chunk_text
    if heading_path:
        trail = " > ".join(heading_path)
        return f"{doc}\n> {trail}\n\n{body}"
    return f"{doc}\n\n{body}"
FENCE_PATTERN = re.compile(r"^\s*(```|~~~)")
LIST_PATTERN = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")
CALLOUT_PATTERN = re.compile(r"^\s*>\s*(?:\[[!A-Za-z]+[^\]]*\])?")
TABLE_PATTERN = re.compile(r"^\s*\|.*\|\s*$")


def _estimate_tokens(text: str) -> int:
    return max(1, int(len(text.split()) * 1.3))


def _word_count(text: str) -> int:
    return len(text.split())


def _block_kind(line: str) -> str:
    if FENCE_PATTERN.match(line):
        return "fence"
    if LIST_PATTERN.match(line):
        return "list"
    if CALLOUT_PATTERN.match(line):
        return "callout"
    if TABLE_PATTERN.match(line):
        return "table"
    return "paragraph"


def _split_markdown_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    current_kind: str | None = None
    in_fence = False
    fence_marker = ""

    def flush() -> None:
        nonlocal current, current_kind
        block = "\n".join(current).strip()
        if block:
            blocks.append(block)
        current = []
        current_kind = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if in_fence:
            current.append(line)
            if stripped.startswith(fence_marker):
                in_fence = False
                flush()
            continue

        fence_match = FENCE_PATTERN.match(line)
        if fence_match:
            if current:
                flush()
            current = [line]
            current_kind = "fence"
            in_fence = True
            fence_marker = fence_match.group(1)
            continue

        if not stripped:
            if current_kind in {"list", "callout", "table"}:
                current.append(line)
            else:
                flush()
            continue

        kind = _block_kind(line)
        if current and current_kind != kind:
            flush()
        current.append(line)
        current_kind = kind

    if current:
        flush()
    return blocks


def _build_sections(text: str) -> list[tuple[str | None, str, int, list[str]]]:
    matches = list(HEADING_PATTERN.finditer(text))
    if not matches:
        stripped = text.strip()
        return [(None, stripped, 0, [])] if stripped else []

    sections: list[tuple[str | None, str, int, list[str]]] = []
    stack: list[tuple[int, str]] = []

    if matches[0].start() > 0:
        preamble = text[: matches[0].start()].strip()
        if preamble:
            sections.append((None, preamble, 0, []))

    for index, match in enumerate(matches):
        level = len(match.group(1))
        title = match.group(2).strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        heading_path = [t for _, t in stack]
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        section_text = f"{title}\n\n{body}".strip() if body else title
        sections.append((title, section_text, match.start(), heading_path))
    return sections


def _split_large_section(
    section_title: str | None,
    heading_path: list[str],
    text: str,
    _start_offset: int,
    max_words: int,
    overlap_paragraphs: int,
) -> list[ChunkRecord]:
    blocks = _split_markdown_blocks(text)
    if not blocks:
        return []

    chunks: list[ChunkRecord] = []
    current: list[str] = []
    current_words = 0

    def _flush(current_blocks: list[str]) -> None:
        chunk_text = "\n\n".join(current_blocks).strip()
        if chunk_text:
            chunks.append(
                ChunkRecord(
                    chunk_index=0,
                    section_title=section_title,
                    text=chunk_text,
                    token_estimate=_estimate_tokens(chunk_text),
                    char_start=0,
                    char_end=0,
                    heading_path=list(heading_path),
                )
            )

    for block in blocks:
        block_words = len(block.split())
        if block_words > max_words:
            if current:
                _flush(current)
                current = []
                current_words = 0
            _flush([block])
            continue

        if current and current_words + block_words > max_words:
            _flush(current)
            overlap = current[-overlap_paragraphs:] if overlap_paragraphs > 0 else []
            current = overlap.copy()
            current_words = sum(len(item.split()) for item in current)

        current.append(block)
        current_words += block_words

    if current:
        _flush(current)
    return chunks


def _combine_chunks(first: ChunkRecord, second: ChunkRecord) -> ChunkRecord:
    combined_text = f"{first.text}\n\n{second.text}".strip()
    if first.heading_path == second.heading_path:
        path = first.heading_path
    elif len(second.heading_path) >= len(first.heading_path):
        path = second.heading_path
    else:
        path = first.heading_path
    return ChunkRecord(
        chunk_index=first.chunk_index,
        section_title=first.section_title or second.section_title,
        text=combined_text,
        token_estimate=_estimate_tokens(combined_text),
        char_start=0,
        char_end=0,
        heading_path=list(path),
    )


def chunk_document(
    text: str,
    target_max_words: int = 800,
    min_words: int = 120,
    overlap_paragraphs: int = 1,
) -> list[ChunkRecord]:
    sections = _build_sections(text)
    raw_chunks: list[ChunkRecord] = []

    for section_title, section_text, offset, heading_path in sections:
        words = len(section_text.split())
        if words <= target_max_words:
            raw_chunks.append(
                ChunkRecord(
                    chunk_index=0,
                    section_title=section_title,
                    text=section_text,
                    token_estimate=_estimate_tokens(section_text),
                    char_start=0,
                    char_end=0,
                    heading_path=list(heading_path),
                )
            )
        else:
            raw_chunks.extend(
                _split_large_section(
                    section_title,
                    heading_path,
                    section_text,
                    offset,
                    target_max_words,
                    overlap_paragraphs,
                )
            )

    merged_chunks: list[ChunkRecord] = []
    pending_small_chunk: ChunkRecord | None = None
    for chunk in raw_chunks:
        if pending_small_chunk is not None:
            combined = _combine_chunks(pending_small_chunk, chunk)
            if _word_count(combined.text) <= target_max_words:
                chunk = combined
            else:
                merged_chunks.append(pending_small_chunk)
            pending_small_chunk = None

        word_count = _word_count(chunk.text)
        if merged_chunks and word_count < min_words:
            combined = _combine_chunks(merged_chunks[-1], chunk)
            if _word_count(combined.text) <= target_max_words:
                merged_chunks[-1] = combined
            else:
                merged_chunks.append(chunk)
            continue
        if word_count < min_words:
            pending_small_chunk = chunk
            continue
        merged_chunks.append(chunk)

    if pending_small_chunk is not None:
        if merged_chunks:
            merged_chunks[-1] = _combine_chunks(merged_chunks[-1], pending_small_chunk)
        else:
            merged_chunks.append(pending_small_chunk)

    for index, chunk in enumerate(merged_chunks):
        chunk.chunk_index = index
    return merged_chunks
