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


def _extract_frontmatter(text: str) -> tuple[dict[str, Any], str, list[str]]:
    match = FRONTMATTER_PATTERN.match(text)
    if not match:
        return {}, text, []
    warnings: list[str] = []
    try:
        payload = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        warnings.append(f"frontmatter YAML could not be parsed: {exc.__class__.__name__}")
        return {}, text[match.end():], warnings
    if payload is None:
        return {}, text[match.end():], warnings
    if not isinstance(payload, dict):
        warnings.append("frontmatter is not a mapping; ignoring")
        return {}, text[match.end():], warnings
    return _json_safe_frontmatter(payload), text[match.end():], warnings


def _normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = [str(item) for item in value if item is not None]
    else:
        items = [str(value)]
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = item.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def _validated_title(value: Any) -> tuple[str | None, list[str]]:
    if value is None:
        return None, []
    if isinstance(value, str):
        return value.strip() or None, []
    return None, ["frontmatter 'title' is not a string; using filename"]


def parse_markdown_file(path: Path) -> tuple[ParsedDocument, list[str]]:
    raw_text = normalize_line_endings(path.read_text(encoding="utf-8"))
    frontmatter, normalized_text, warnings = _extract_frontmatter(raw_text)

    title_value, title_warnings = _validated_title(frontmatter.get("title"))
    warnings.extend(title_warnings)

    raw_tags = frontmatter.get("tags")
    if raw_tags is not None and not isinstance(raw_tags, (str, list)):
        warnings.append("frontmatter 'tags' is not a string or list; coercing")

    raw_aliases = frontmatter.get("aliases")
    if raw_aliases is not None and not isinstance(raw_aliases, (str, list)):
        warnings.append("frontmatter 'aliases' is not a string or list; coercing")

    tags = _normalize_string_list(raw_tags)
    aliases = _normalize_string_list(raw_aliases)
    if title_value is not None:
        frontmatter["title"] = title_value
    title = infer_title(path, frontmatter)
    document = ParsedDocument(
        source_path=path,
        title=title,
        raw_text=raw_text,
        normalized_text=normalized_text.strip(),
        frontmatter=frontmatter,
        tags=tags,
        aliases=aliases,
    )
    return document, warnings
