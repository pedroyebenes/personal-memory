from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Iterable


@dataclass(slots=True)
class ScannedFile:
    path: Path
    size: int
    mtime_iso: str


def _matches_any(relative_path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch(relative_path, pattern) for pattern in patterns)


def scan_markdown_files(
    vault_path: Path,
    *,
    include: Iterable[str] | None = None,
    exclude: Iterable[str] | None = None,
) -> list[Path]:
    include_patterns = tuple(include or ())
    exclude_patterns = tuple(exclude or ())
    paths: list[Path] = []
    for path in vault_path.rglob("*.md"):
        if not path.is_file():
            continue
        try:
            relative = str(path.relative_to(vault_path))
        except ValueError:
            relative = path.name
        if include_patterns and not _matches_any(relative, include_patterns):
            continue
        if exclude_patterns and _matches_any(relative, exclude_patterns):
            continue
        paths.append(path)
    return sorted(paths)


def scan_markdown_entries(
    vault_path: Path,
    *,
    include: Iterable[str] | None = None,
    exclude: Iterable[str] | None = None,
) -> list[ScannedFile]:
    from datetime import datetime, timezone

    entries: list[ScannedFile] = []
    for path in scan_markdown_files(vault_path, include=include, exclude=exclude):
        try:
            stat = path.stat()
        except OSError:
            continue
        mtime_iso = (
            datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            .replace(microsecond=0)
            .isoformat()
        )
        entries.append(ScannedFile(path=path, size=int(stat.st_size), mtime_iso=mtime_iso))
    return entries
