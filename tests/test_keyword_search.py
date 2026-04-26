from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.ingest.register import ingest_vault
from app.retrieval.keyword_search import _build_fts_query, keyword_search


def test_build_fts_query_single_token_is_or_of_one() -> None:
    assert _build_fts_query("Hello") == '"hello"'


def test_build_fts_query_multi_token_adds_near_clause() -> None:
    q = _build_fts_query("Don Quijote")
    assert "NEAR(" in q
    assert '"don"' in q
    assert '"quijote"' in q
    assert " OR " in q


def test_weighted_keyword_search_prefers_section_hit_over_body_only(
    connection, tmp_path: Path, settings: Settings
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    token = "UniqueSectionWeightToken42"
    (vault / "in_section.md").write_text(
        f"---\ntitle: Book A\n---\n\n# {token}\n\nFiller body without extra markers.\n",
        encoding="utf-8",
    )
    (vault / "in_body.md").write_text(
        f"---\ntitle: Book B\n---\n\n# Other Heading\n\nThe {token} appears only in body text.\n",
        encoding="utf-8",
    )
    ingest_vault(connection, vault, settings)

    results = keyword_search(connection, token, top_k=5)
    paths = [r.source_path for r in results]
    sec_idx = next(i for i, p in enumerate(paths) if "in_section" in p)
    body_idx = next(i for i, p in enumerate(paths) if "in_body" in p)
    assert sec_idx < body_idx


def test_keyword_search_prefers_proximate_phrase_for_two_tokens(
    connection, tmp_path: Path, settings: Settings
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "close.md").write_text(
        "---\ntitle: Close\n---\n\n# Intro\n\nalpha beta gamma phrase pair together.\n",
        encoding="utf-8",
    )
    (vault / "far.md").write_text(
        "---\ntitle: Far\n---\n\n# Intro\n\nalpha one two three four five six seven eight nine gamma beta spread.\n",
        encoding="utf-8",
    )
    ingest_vault(connection, vault, settings)

    results = keyword_search(connection, "alpha beta", top_k=5)
    paths = [r.source_path for r in results]
    close_idx = next(i for i, p in enumerate(paths) if "close" in p)
    far_idx = next(i for i, p in enumerate(paths) if "far" in p)
    assert close_idx < far_idx
