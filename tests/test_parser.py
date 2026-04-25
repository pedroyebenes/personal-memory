from __future__ import annotations

from datetime import date
from pathlib import Path

from app.util.hashing import sha256_text
from app.vault.obsidian_parser import infer_title, parse_markdown_file


def test_frontmatter_parsing(fixture_vault: Path) -> None:
    parsed, warnings = parse_markdown_file(fixture_vault / "project-note.md")
    assert parsed.title == "Project North Star"
    assert parsed.tags == ["project", "planning"]
    assert parsed.aliases == ["North Star", "Launch Plan"]
    assert parsed.normalized_text.startswith("# Overview")
    assert warnings == []


def test_title_inference_from_filename() -> None:
    title = infer_title(Path("daily_note.md"), {})
    assert title == "daily note"


def test_change_detection_by_hash() -> None:
    assert sha256_text("abc") == sha256_text("abc")
    assert sha256_text("abc") != sha256_text("abcd")


def test_frontmatter_dates_are_normalized_to_strings(tmp_path: Path) -> None:
    note = tmp_path / "dated-note.md"
    note.write_text(
        "---\n"
        "title: Dated Note\n"
        "created: 2026-04-22\n"
        "metadata:\n"
        "  reviewed: 2026-04-23\n"
        "---\n"
        "# Body\n",
        encoding="utf-8",
    )

    parsed, _ = parse_markdown_file(note)

    assert parsed.frontmatter["created"] == "2026-04-22"
    assert parsed.frontmatter["metadata"]["reviewed"] == "2026-04-23"
    assert not isinstance(parsed.frontmatter["created"], date)
