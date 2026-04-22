from __future__ import annotations

from pathlib import Path


def scan_markdown_files(vault_path: Path) -> list[Path]:
    return sorted(path for path in vault_path.rglob("*.md") if path.is_file())
