from __future__ import annotations

from app.vault.obsidian_parser import normalize_line_endings


def normalize_markdown(text: str) -> str:
    return normalize_line_endings(text).strip()
