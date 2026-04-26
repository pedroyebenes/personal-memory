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


def test_cluster_payload_has_representatives_and_top_documents(
    connection, fixture_vault: Path, settings: Settings
) -> None:
    ingest_vault(connection, fixture_vault, settings)
    payload = _compute_viz_data(connection)

    assert payload["projection"] in {"umap", "pca"}
    assert payload["clusters"], "expected at least one cluster"

    chunk_ids = {int(p["id"]) for p in payload["points"]}
    doc_ids = {int(p["document_id"]) for p in payload["points"]}

    for cluster in payload["clusters"]:
        assert cluster["size"] > 0
        assert 0.0 <= float(cluster["coherence"]) <= 1.0
        assert isinstance(cluster["is_noise"], bool)
        assert isinstance(cluster["terms"], list)

        reps = cluster["representatives"]
        assert reps, f"cluster {cluster['id']} has no representatives"
        assert len(reps) <= 3
        for rep in reps:
            assert int(rep["chunk_id"]) in chunk_ids
            assert "snippet" in rep
            assert "document_title" in rep

        docs = cluster["top_documents"]
        assert docs, f"cluster {cluster['id']} has no top documents"
        assert len(docs) <= 5
        assert sum(int(d["count"]) for d in docs) <= cluster["size"]
        for doc in docs:
            assert int(doc["document_id"]) in doc_ids
            assert isinstance(doc["title"], str)


def test_distinctive_labels_prefer_rare_terms_over_common(
    connection, tmp_path: Path, settings: Settings
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    # ``Meeting Notes`` appears in every file → should NOT dominate any cluster.
    # ``Quantum Entanglement`` is unique to one file → must surface as distinctive.
    (vault / "general-1.md").write_text(
        "# Weekly\n\nFrom [[Meeting Notes]]: tasks discussed. [[Meeting Notes]] continued.\n",
        encoding="utf-8",
    )
    (vault / "general-2.md").write_text(
        "# Weekly\n\n[[Meeting Notes]] again. Another [[Meeting Notes]] entry.\n",
        encoding="utf-8",
    )
    (vault / "general-3.md").write_text(
        "# Weekly\n\nMore [[Meeting Notes]] chatter and [[Meeting Notes]] minutes.\n",
        encoding="utf-8",
    )
    (vault / "physics.md").write_text(
        "# Physics\n\nNotes on [[Quantum Entanglement]] and more [[Quantum Entanglement]] work.\n",
        encoding="utf-8",
    )

    ingest_vault(connection, vault, settings)
    payload = _compute_viz_data(connection)

    all_terms = {term.lower() for cluster in payload["clusters"] for term in cluster["terms"]}
    assert "quantum entanglement" in all_terms, (
        "distinctive label should surface the rare concept: " f"clusters={payload['clusters']}"
    )

    physics_clusters = [
        c for c in payload["clusters"]
        if any("quantum entanglement" in t.lower() for t in c["terms"])
    ]
    assert physics_clusters, "rare term should be among the terms of at least one cluster"
    best = physics_clusters[0]
    ranks = [t.lower() for t in best["terms"]]
    if "meeting notes" in ranks:
        assert ranks.index("quantum entanglement") < ranks.index("meeting notes")


def test_supercluster_payload_is_well_formed(
    connection, fixture_vault: Path, settings: Settings
) -> None:
    ingest_vault(connection, fixture_vault, settings)
    payload = _compute_viz_data(connection)

    assert "superclusters" in payload
    supers = payload["superclusters"]
    assert isinstance(supers, list)
    # Superclusters are optional (need >=4 proper clusters) but when present the
    # schema must be coherent with the cluster payload.
    if supers:
        cluster_ids = {c["id"] for c in payload["clusters"]}
        seen_cluster_ids: set[int] = set()
        super_ids = set()
        for sc in supers:
            assert "id" in sc and isinstance(sc["id"], int)
            assert sc["id"] not in super_ids, "duplicate supercluster id"
            super_ids.add(sc["id"])
            assert isinstance(sc["name"], str) and sc["name"].strip()
            assert isinstance(sc["size"], int) and sc["size"] > 0
            assert isinstance(sc["is_noise"], bool)
            assert isinstance(sc["terms"], list)
            assert isinstance(sc["cluster_ids"], list) and sc["cluster_ids"]
            center = sc["center"]
            assert isinstance(center, list) and len(center) == 3
            for coord in center:
                assert isinstance(coord, float)
            for cid in sc["cluster_ids"]:
                assert cid in cluster_ids
                assert cid not in seen_cluster_ids, "cluster assigned to multiple superclusters"
                seen_cluster_ids.add(cid)

        # Every cluster referenced by a supercluster should back-reference it.
        by_cluster_super = {c["id"]: c.get("supercluster_id") for c in payload["clusters"]}
        for sc in supers:
            for cid in sc["cluster_ids"]:
                assert by_cluster_super.get(cid) == sc["id"]
