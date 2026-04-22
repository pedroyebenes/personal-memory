from __future__ import annotations

from app.processing.chunker import chunk_document


def test_chunking_preserves_section_titles() -> None:
    text = "# One\n\nalpha beta gamma\n\n# Two\n\n" + "word " * 150
    chunks = chunk_document(text, target_max_words=120, min_words=20)
    assert len(chunks) >= 2
    assert chunks[0].section_title == "One"
    assert any(chunk.section_title == "Two" for chunk in chunks)


def test_chunking_merges_tiny_sections() -> None:
    text = "# One\n\nsmall text\n\n# Two\n\n" + "word " * 140
    chunks = chunk_document(text, target_max_words=300, min_words=30)
    assert len(chunks) == 1
