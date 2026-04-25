from __future__ import annotations

import re

from app.models import ChunkRecord

HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)
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


def _build_sections(text: str) -> list[tuple[str | None, str, int]]:
    matches = list(HEADING_PATTERN.finditer(text))
    if not matches:
        return [(None, text.strip(), 0)] if text.strip() else []

    sections: list[tuple[str | None, str, int]] = []
    if matches[0].start() > 0:
        preamble = text[:matches[0].start()].strip()
        if preamble:
            sections.append((None, preamble, 0))

    for index, match in enumerate(matches):
        title = match.group(2).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        section_text = f"{title}\n\n{body}".strip() if body else title
        sections.append((title, section_text, match.start()))
    return sections


def _split_large_section(
    section_title: str | None,
    text: str,
    start_offset: int,
    max_words: int,
    overlap_paragraphs: int,
) -> list[ChunkRecord]:
    blocks = _split_markdown_blocks(text)
    if not blocks:
        return []

    chunks: list[ChunkRecord] = []
    current: list[str] = []
    current_words = 0
    chunk_start = start_offset
    running_offset = start_offset

    for block in blocks:
        block_words = len(block.split())
        if block_words > max_words:
            if current:
                chunk_text = "\n\n".join(current).strip()
                chunks.append(
                    ChunkRecord(
                        chunk_index=0,
                        section_title=section_title,
                        text=chunk_text,
                        token_estimate=_estimate_tokens(chunk_text),
                        char_start=chunk_start,
                        char_end=chunk_start + len(chunk_text),
                    )
                )
                current = []
                current_words = 0
                chunk_start = running_offset
            chunks.append(
                ChunkRecord(
                    chunk_index=0,
                    section_title=section_title,
                    text=block,
                    token_estimate=_estimate_tokens(block),
                    char_start=running_offset,
                    char_end=running_offset + len(block),
                )
            )
            running_offset += len(block) + 2
            chunk_start = running_offset
            continue

        if current and current_words + block_words > max_words:
            chunk_text = "\n\n".join(current).strip()
            chunks.append(
                ChunkRecord(
                    chunk_index=0,
                    section_title=section_title,
                    text=chunk_text,
                    token_estimate=_estimate_tokens(chunk_text),
                    char_start=chunk_start,
                    char_end=chunk_start + len(chunk_text),
                )
            )
            overlap = current[-overlap_paragraphs:] if overlap_paragraphs > 0 else []
            current = overlap.copy()
            current_words = sum(len(item.split()) for item in current)
            chunk_start = running_offset - len("\n\n".join(overlap)) if overlap else running_offset

        current.append(block)
        current_words += block_words
        running_offset += len(block) + 2

    if current:
        chunk_text = "\n\n".join(current).strip()
        chunks.append(
            ChunkRecord(
                chunk_index=0,
                section_title=section_title,
                text=chunk_text,
                token_estimate=_estimate_tokens(chunk_text),
                char_start=chunk_start,
                char_end=chunk_start + len(chunk_text),
            )
        )
    return chunks


def _combine_chunks(first: ChunkRecord, second: ChunkRecord) -> ChunkRecord:
    combined_text = f"{first.text}\n\n{second.text}".strip()
    return ChunkRecord(
        chunk_index=first.chunk_index,
        section_title=first.section_title or second.section_title,
        text=combined_text,
        token_estimate=_estimate_tokens(combined_text),
        char_start=first.char_start,
        char_end=second.char_end,
    )


def chunk_document(
    text: str,
    target_max_words: int = 800,
    min_words: int = 120,
    overlap_paragraphs: int = 1,
) -> list[ChunkRecord]:
    sections = _build_sections(text)
    raw_chunks: list[ChunkRecord] = []

    for section_title, section_text, offset in sections:
        words = len(section_text.split())
        if words <= target_max_words:
            raw_chunks.append(
                ChunkRecord(
                    chunk_index=0,
                    section_title=section_title,
                    text=section_text,
                    token_estimate=_estimate_tokens(section_text),
                    char_start=offset,
                    char_end=offset + len(section_text),
                )
            )
        else:
            raw_chunks.extend(
                _split_large_section(section_title, section_text, offset, target_max_words, overlap_paragraphs)
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
