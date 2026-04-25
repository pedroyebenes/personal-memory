from __future__ import annotations

import re

TERM_PATTERN = re.compile(r"[A-Za-z0-9_]+")


def query_terms(query: str) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for term in TERM_PATTERN.findall(query.lower()):
        if term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _trim_around_match(text: str, terms: list[str], max_chars: int) -> str:
    compact = _compact(text)
    if len(compact) <= max_chars:
        return compact

    lower = compact.lower()
    positions = [lower.find(term) for term in terms if lower.find(term) >= 0]
    if not positions:
        return compact[:max_chars].rstrip()

    first_match = min(positions)
    start = max(0, first_match - max_chars // 3)
    end = min(len(compact), start + max_chars)
    start = max(0, end - max_chars)
    snippet = compact[start:end].strip()
    if start > 0:
        snippet = "... " + snippet.lstrip()
    if end < len(compact):
        snippet = snippet.rstrip() + " ..."
    return snippet


def extract_snippet(text: str, query: str, max_chars: int = 280) -> str:
    terms = query_terms(query)
    if not terms:
        return _trim_around_match(text, [], max_chars)

    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    if not blocks:
        return ""

    best_block = blocks[0]
    best_score = -1
    query_lower = query.lower().strip()
    for index, block in enumerate(blocks):
        lower = block.lower()
        score = sum(lower.count(term) for term in terms)
        if query_lower and query_lower in lower:
            score += 3
        if score > best_score:
            best_score = score
            best_block = block
        elif score == best_score and index == 0:
            best_block = block

    if best_score <= 0:
        best_block = text
    return _trim_around_match(best_block, terms, max_chars)
