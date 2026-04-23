from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from app.models import ParsedDocument

FRONTMATTER_PATTERN = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)


def normalize_line_endings(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def infer_title(source_path: Path, frontmatter: dict[str, Any]) -> str:
    title = frontmatter.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return source_path.stem.replace("_", " ").strip()


def _json_safe_frontmatter(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_safe_frontmatter(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe_frontmatter(item) for key, item in value.items()}
    return str(value)


def _extract_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = FRONTMATTER_PATTERN.match(text)
    if not match:
        return {}, text
    payload = yaml.safe_load(match.group(1)) or {}
    if not isinstance(payload, dict):
        payload = {}
    return _json_safe_frontmatter(payload), text[match.end():]


def _normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def parse_markdown_file(path: Path) -> ParsedDocument:
    raw_text = normalize_line_endings(path.read_text(encoding="utf-8"))
    frontmatter, normalized_text = _extract_frontmatter(raw_text)
    tags = _normalize_string_list(frontmatter.get("tags"))
    aliases = _normalize_string_list(frontmatter.get("aliases"))
    title = infer_title(path, frontmatter)
    return ParsedDocument(
        source_path=path,
        title=title,
        raw_text=raw_text,
        normalized_text=normalized_text.strip(),
        frontmatter=frontmatter,
        tags=tags,
        aliases=aliases,
    )
