from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.ingest.register import ingest_vault, refresh_concepts
from app.processing.entity_embedding_sync import sync_entity_embeddings
from app.retrieval.concept_search import semantic_concept_search


def test_ingest_populates_entity_embeddings_for_promoted_concepts(
    connection, tmp_path: Path, settings: Settings
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "a.md").write_text(
        "---\ntitle: A\n---\n\n# X\n\n[[Fortune]] speaks of destiny.\n",
        encoding="utf-8",
    )
    (vault / "c.md").write_text(
        "---\ntitle: C\n---\n\n# Z\n\n[[Fortune]] second document for mention count.\n",
        encoding="utf-8",
    )
    (vault / "b.md").write_text(
        "---\ntitle: B\n---\n\n# Y\n\n[[Fate]] mirrors destiny.\n",
        encoding="utf-8",
    )
    (vault / "d.md").write_text(
        "---\ntitle: D\n---\n\n# W\n\n[[Fate]] second document.\n",
        encoding="utf-8",
    )
    summary = ingest_vault(connection, vault, settings)
    assert summary.get("entity_embeddings", {}).get("updated", 0) >= 1

    rows = connection.execute(
        """
        SELECT COUNT(*) AS c FROM entity_embeddings ee
        JOIN entities e ON e.id = ee.entity_id
        WHERE e.canonical_name IN ('Fortune', 'Fate')
        """
    ).fetchone()
    assert int(rows["c"]) >= 1


def test_sync_skips_unchanged_content_hash(connection, tmp_path: Path, settings: Settings) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "n1.md").write_text(
        "---\ntitle: T1\n---\n\n# H\n\n[[StableConcept]] one.\n",
        encoding="utf-8",
    )
    (vault / "n2.md").write_text(
        "---\ntitle: T2\n---\n\n# H\n\n[[StableConcept]] two.\n",
        encoding="utf-8",
    )
    ingest_vault(connection, vault, settings)
    second = sync_entity_embeddings(connection, settings)
    assert second["updated"] == 0
    assert second["skipped"] >= 1


def test_semantic_concept_search_ranks_related_concepts(
    connection, tmp_path: Path, settings: Settings
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "fortune.md").write_text(
        (
            "---\ntitle: Fortune Note\n---\n\n# F\n\n"
            "[[Fortune]] is tied to destiny and fate.\n"
        ),
        encoding="utf-8",
    )
    (vault / "fortune2.md").write_text(
        "---\ntitle: Fortune2\n---\n\n# F\n\n[[Fortune]] more destiny context.\n",
        encoding="utf-8",
    )
    (vault / "fate.md").write_text(
        (
            "---\ntitle: Fate Note\n---\n\n# G\n\n"
            "[[Fate]] follows destiny patterns.\n"
        ),
        encoding="utf-8",
    )
    (vault / "fate2.md").write_text(
        "---\ntitle: Fate2\n---\n\n# G\n\n[[Fate]] more patterns.\n",
        encoding="utf-8",
    )
    ingest_vault(connection, vault, settings)

    ranked = semantic_concept_search(connection, "destiny fortune fate", settings, top_k=5)
    names = [r["canonical_name"] for r in ranked]
    assert "Fortune" in names or "Fate" in names


def test_delete_entity_removes_embedding_row(connection, tmp_path: Path, settings: Settings) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "z1.md").write_text(
        "---\ntitle: Z1\n---\n\n# Z\n\n[[Zap]] a.\n",
        encoding="utf-8",
    )
    (vault / "z2.md").write_text(
        "---\ntitle: Z2\n---\n\n# Z\n\n[[Zap]] b.\n",
        encoding="utf-8",
    )
    ingest_vault(connection, vault, settings)
    row = connection.execute("SELECT id FROM entities WHERE canonical_name = 'Zap'").fetchone()
    assert row is not None
    eid = int(row["id"])
    emb = connection.execute(
        "SELECT 1 FROM entity_embeddings WHERE entity_id = ?", (eid,)
    ).fetchone()
    assert emb is not None
    connection.execute("DELETE FROM entities WHERE id = ?", (eid,))
    connection.commit()
    assert (
        connection.execute(
            "SELECT 1 FROM entity_embeddings WHERE entity_id = ?", (eid,)
        ).fetchone()
        is None
    )


def test_refresh_concepts_reports_entity_embedding_stats(
    connection, fixture_vault: Path, settings: Settings
) -> None:
    ingest_vault(connection, fixture_vault, settings)
    out = refresh_concepts(connection, settings)
    assert "entity_embeddings" in out
    stats = out["entity_embeddings"]
    assert "updated" in stats
    assert int(connection.execute("SELECT COUNT(*) AS c FROM entity_embeddings").fetchone()["c"]) >= 1
