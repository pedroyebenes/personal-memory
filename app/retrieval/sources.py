from __future__ import annotations

import re


def heading_anchor(section_title: str | None) -> str | None:
    if not section_title:
        return None
    anchor = re.sub(r"[^a-z0-9 -]", "", section_title.lower())
    anchor = re.sub(r"\s+", "-", anchor.strip())
    return anchor or None


def build_source_ref(source_path: str, section_title: str | None = None) -> str:
    anchor = heading_anchor(section_title)
    return f"{source_path}#{anchor}" if anchor else source_path


def build_markdown_ref(document_title: str, source_path: str, section_title: str | None = None) -> str:
    source_ref = build_source_ref(source_path, section_title)
    label = f"{document_title} > {section_title}" if section_title else document_title
    return f"[{label}]({source_ref})"
