from __future__ import annotations

from pathlib import Path

from app.util.hashing import sha256_text
from app.vault.obsidian_parser import infer_title, parse_markdown_file


def test_frontmatter_parsing(fixture_vault: Path) -> None:
    parsed = parse_markdown_file(fixture_vault / "project-note.md")
    assert parsed.title == "Project North Star"
    assert parsed.tags == ["project", "planning"]
    assert parsed.aliases == ["North Star", "Launch Plan"]
    assert parsed.normalized_text.startswith("# Overview")


def test_title_inference_from_filename() -> None:
    title = infer_title(Path("daily_note.md"), {})
    assert title == "daily note"


def test_change_detection_by_hash() -> None:
    assert sha256_text("abc") == sha256_text("abc")
    assert sha256_text("abc") != sha256_text("abcd")
