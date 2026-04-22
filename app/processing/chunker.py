from __future__ import annotations

import re

from app.models import ChunkRecord

HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)


def _estimate_tokens(text: str) -> int:
    return max(1, int(len(text.split()) * 1.3))


def _split_paragraphs(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]


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
    paragraphs = _split_paragraphs(text)
    if not paragraphs:
        return []

    chunks: list[ChunkRecord] = []
    current: list[str] = []
    current_words = 0
    chunk_start = start_offset
    running_offset = start_offset

    for paragraph in paragraphs:
        paragraph_words = len(paragraph.split())
        if current and current_words + paragraph_words > max_words:
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

        current.append(paragraph)
        current_words += paragraph_words
        running_offset += len(paragraph) + 2

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
    for chunk in raw_chunks:
        word_count = len(chunk.text.split())
        if merged_chunks and word_count < min_words:
            previous = merged_chunks[-1]
            previous.text = f"{previous.text}\n\n{chunk.text}".strip()
            previous.token_estimate = _estimate_tokens(previous.text)
            previous.char_end = chunk.char_end
            if previous.section_title is None:
                previous.section_title = chunk.section_title
            continue
        merged_chunks.append(chunk)

    for index, chunk in enumerate(merged_chunks):
        chunk.chunk_index = index
    return merged_chunks
