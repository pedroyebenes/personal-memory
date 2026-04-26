from __future__ import annotations

from app.processing.chunker import breadcrumb_text, chunk_document


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


def test_chunking_keeps_fenced_code_blocks_intact() -> None:
    code = "\n".join(f"print('line {index}')" for index in range(30))
    text = f"# Implementation\n\nIntro text.\n\n```python\n{code}\n```\n\nFinal note."

    chunks = chunk_document(text, target_max_words=20, min_words=1)

    code_chunks = [chunk for chunk in chunks if "```python" in chunk.text]
    assert len(code_chunks) == 1
    assert "print('line 0')" in code_chunks[0].text
    assert "print('line 29')" in code_chunks[0].text
    assert code_chunks[0].text.count("```") == 2


def test_chunking_keeps_lists_and_callouts_as_blocks() -> None:
    list_items = "\n".join(f"- Task {index} needs structured chunking" for index in range(12))
    callout = "\n".join(
        [
            "> [!note] Retrieval quality",
            "> Preserve this callout when splitting large notes.",
            "> It should not be separated line-by-line.",
        ]
    )
    text = f"# Planning\n\nIntro text.\n\n{list_items}\n\n{callout}\n\nClosing text."

    chunks = chunk_document(text, target_max_words=24, min_words=1)

    list_chunks = [chunk for chunk in chunks if "- Task 0" in chunk.text]
    callout_chunks = [chunk for chunk in chunks if "[!note]" in chunk.text]
    assert len(list_chunks) == 1
    assert "- Task 11" in list_chunks[0].text
    assert len(callout_chunks) == 1
    assert "It should not be separated" in callout_chunks[0].text


def test_chunk_heading_path_tracks_heading_stack() -> None:
    text = "# A\n\npara one\n\n## B\n\npara two\n\n### C\n\npara three.\n"
    chunks = chunk_document(text, target_max_words=800, min_words=1)
    paths = {tuple(c.heading_path) for c in chunks}
    assert ("A",) in paths
    assert ("A", "B") in paths
    assert ("A", "B", "C") in paths


def test_breadcrumb_text_includes_title_and_trail() -> None:
    s = breadcrumb_text("Don Quijote", ["Capítulo IV", "Aventura"], "body")
    assert s == "Don Quijote\n> Capítulo IV > Aventura\n\nbody"


def test_breadcrumb_text_without_path_is_title_only() -> None:
    s = breadcrumb_text("Book", [], "hello")
    assert s == "Book\n\nhello"


def test_chunk_text_not_mutated_by_breadcrumb() -> None:
    chunks = chunk_document("# A\n\nhello world", target_max_words=500, min_words=1)
    assert chunks[0].text == "A\n\nhello world"
    wrapped = breadcrumb_text("T", chunks[0].heading_path, chunks[0].text)
    assert wrapped.endswith(chunks[0].text)
    assert chunks[0].text == "A\n\nhello world"
