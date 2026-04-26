from __future__ import annotations

import json
from pathlib import Path

from app.config import Settings
from app.ingest.register import ingest_vault
from app.web import _compute_viz_data


def test_compute_viz_top_concept_stable_json(connection, fixture_vault: Path, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)
    first = _compute_viz_data(connection)
    second = _compute_viz_data(connection)
    assert json.dumps(first["points"], sort_keys=True) == json.dumps(second["points"], sort_keys=True)
    assert json.dumps(first["clusters"], sort_keys=True) == json.dumps(second["clusters"], sort_keys=True)


def test_compute_viz_top_concept_prefers_wikilink_over_tag(
    connection, fixture_vault: Path, settings: Settings
) -> None:
    ingest_vault(connection, fixture_vault, settings)
    row = connection.execute(
        """
        SELECT c.id
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.source_path LIKE '%wiki-links%'
        ORDER BY c.chunk_index
        LIMIT 1
        """
    ).fetchone()
    assert row is not None
    chunk_id = int(row["id"])

    payload = _compute_viz_data(connection)
    point = next(p for p in payload["points"] if int(p["id"]) == chunk_id)
    assert point.get("top_concept") is not None
    assert point["top_concept"]["method"] == "wikilink"
    assert "north star" in point["top_concept"]["canonical_name"].lower()


def test_compute_viz_cluster_name_favors_concepts_over_chapter_heading(
    connection, tmp_path: Path, settings: Settings
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "book.md").write_text(
        "# CAPÍTULO I\n\nPara [[Hero Name]] y otra vez [[Hero Name]].\n",
        encoding="utf-8",
    )
    ingest_vault(connection, vault, settings)
    payload = _compute_viz_data(connection)
    assert any("hero name" in c["name"].lower() for c in payload["clusters"])


def test_compute_viz_survives_empty_concept_layer(connection, fixture_vault: Path, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)
    connection.execute("DELETE FROM entity_mentions")
    connection.execute("DELETE FROM entities")
    connection.commit()

    payload = _compute_viz_data(connection)
    assert payload["points"]
    assert payload["clusters"]
    assert not any(p.get("top_concept") for p in payload["points"])
    assert all(c.get("name") for c in payload["clusters"])
