from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections import Counter
from dataclasses import asdict, replace
from datetime import date, datetime, time, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.config import Settings, normalize_provider_name, supported_llm_providers_list
from app.db import connect, init_db
from app.ingest.register import ingest_vault, refresh_concepts, status_summary
from app.models import SearchFilters
from app.processing.concepts import classify_entity_type, normalize_key
from app.retrieval.concept_search import (
    CONCEPT_QUALITIES,
    get_concept_detail,
    list_concepts,
    semantic_concept_search,
)
from app.retrieval.evaluation import evaluate_retrieval_cases
from app.retrieval.hybrid_search import hybrid_search
from app.retrieval.qa import answer_question
from app.util.timestamps import utc_now_iso

WEB_ASSETS_ROOT = Path(__file__).with_name("web_assets").resolve()

STATIC_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".webp": "image/webp",
    ".woff2": "font/woff2",
    ".ico": "image/x-icon",
    ".map": "application/json; charset=utf-8",
}


def _resolve_static(rel: str) -> Path | None:
    """Resolve a static asset path under web_assets/ with traversal protection.

    Returns None if the path escapes the web_assets directory, points at a
    non-file, or has an extension we do not serve.
    """
    if not rel or "\x00" in rel:
        return None
    cleaned = rel.lstrip("/")
    candidate = (WEB_ASSETS_ROOT / cleaned).resolve()
    try:
        candidate.relative_to(WEB_ASSETS_ROOT)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    if candidate.suffix.lower() not in STATIC_CONTENT_TYPES:
        return None
    return candidate


def _read_web_asset(name: str) -> str:
    """Read a static asset as text (kept for compatibility with existing tests)."""
    candidate = _resolve_static(name)
    if candidate is None:
        raise FileNotFoundError(name)
    return candidate.read_text(encoding="utf-8")


class APIError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: HTTPStatus,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details or {}


class RefreshState:
    def __init__(self) -> None:
        self._refresh_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._in_progress = False
        self._started_at: str | None = None
        self._last_completed_at: str | None = None
        self._last_result: dict[str, object] | None = None

    def begin(self) -> None:
        if not self._refresh_lock.acquire(blocking=False):
            raise APIError(
                "refresh_in_progress",
                "A refresh is already running.",
                status=HTTPStatus.CONFLICT,
            )
        with self._state_lock:
            self._in_progress = True
            self._started_at = utc_now_iso()
            self._last_result = None

    def finish(self, result: dict[str, object]) -> None:
        with self._state_lock:
            self._in_progress = False
            self._last_completed_at = utc_now_iso()
            self._last_result = dict(result)
            self._started_at = None
        self._refresh_lock.release()

    def snapshot(self) -> dict[str, object]:
        with self._state_lock:
            return {
                "in_progress": self._in_progress,
                "started_at": self._started_at,
                "last_completed_at": self._last_completed_at,
                "last_result": self._last_result,
            }


def _truncate(text: str, limit: int = 220) -> str:
    flat = text.replace("\n", " ")
    if len(flat) <= limit:
        return flat
    return flat[:limit].rsplit(" ", 1)[0] + "…"


_VIZ_CAPITALIZED_PHRASE = re.compile(
    r"\b([A-ZÁÉÍÓÚÜÑ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9'’/-]*(?:\s+[A-ZÁÉÍÓÚÜÑ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9'’/-]*){1,4})\b"
)
_VIZ_LABEL_STOP_NORMALIZED = frozenset({"text", "notes", "untitled"})

# Order for picking a single ``top_concept`` per chunk (earlier = higher priority).
VIZ_CONCEPT_METHOD_PRIORITY: tuple[str, ...] = (
    "wikilink",
    "alias",
    "tag",
    "definition",
    "inline_tag",
    "emphasis",
    "body_phrase",
    "heading",
)
_VIZ_METHOD_PRIORITY_INDEX: dict[str, int] = {m: i for i, m in enumerate(VIZ_CONCEPT_METHOD_PRIORITY)}


def _load_chunk_concept_mentions(
    conn: sqlite3.Connection, chunk_ids: list[int]
) -> dict[int, list[sqlite3.Row]]:
    if not chunk_ids:
        return {}
    placeholders = ",".join("?" for _ in chunk_ids)
    rows = conn.execute(
        f"""
        SELECT em.chunk_id, em.extraction_method, em.entity_id,
               e.canonical_name, e.mention_count
        FROM entity_mentions em
        JOIN entities e ON e.id = em.entity_id
        WHERE em.chunk_id IN ({placeholders})
          AND (e.entity_type IS NULL OR e.entity_type = 'concept')
        """,
        chunk_ids,
    ).fetchall()
    by_chunk: dict[int, list[sqlite3.Row]] = {}
    for row in rows:
        cid = int(row["chunk_id"])
        by_chunk.setdefault(cid, []).append(row)
    return by_chunk


def _viz_top_concept_payload(mentions: list[sqlite3.Row]) -> dict[str, object] | None:
    if not mentions:
        return None
    best = min(
        mentions,
        key=lambda r: (
            _VIZ_METHOD_PRIORITY_INDEX.get(str(r["extraction_method"]), 1000),
            -int(r["mention_count"] or 0),
        ),
    )
    return {
        "id": int(best["entity_id"]),
        "canonical_name": str(best["canonical_name"]),
        "method": str(best["extraction_method"]),
    }


def _cluster_name_from_entity_centroid(
    conn: sqlite3.Connection,
    cluster_row_indices: list[int],
    vectors: Any,
    *,
    min_chunks: int = 3,
) -> dict[str, object] | None:
    if len(cluster_row_indices) < min_chunks:
        return None
    import numpy as np

    from app.processing.embeddings import cosine_similarity

    centroid = vectors[cluster_row_indices].mean(axis=0).astype(np.float64)
    centroid_list = centroid.tolist()
    rows = conn.execute(
        """
        SELECT ee.vector_json, e.canonical_name
        FROM entity_embeddings ee
        JOIN entities e ON e.id = ee.entity_id
        WHERE (e.entity_type = 'concept' OR e.entity_type IS NULL)
        """
    ).fetchall()
    if not rows:
        return None
    scored: list[tuple[float, str]] = []
    for row in rows:
        vec = json.loads(row["vector_json"])
        if not isinstance(vec, list):
            continue
        s = cosine_similarity(centroid_list, [float(x) for x in vec])
        scored.append((s, str(row["canonical_name"])))
    scored.sort(key=lambda item: -item[0])
    if not scored or scored[0][0] < 0.01:
        return None
    top_s = scored[0][0]
    names = [n for s, n in scored if s >= top_s * 0.88][:5]
    if not names:
        names = [scored[0][1]]
    return {
        "name": " / ".join(names[:2]),
        "terms": names[:5],
        "size": len(cluster_row_indices),
    }


def _cluster_name_from_chunk_concepts(
    chunk_ids: list[int],
    by_chunk: dict[int, list[sqlite3.Row]],
    fallback_rows: list[sqlite3.Row],
    *,
    conn: sqlite3.Connection | None = None,
    cluster_row_indices: list[int] | None = None,
    vectors: Any | None = None,
) -> dict[str, object]:
    counter: Counter[str] = Counter()
    for cid in chunk_ids:
        for row in by_chunk.get(cid, []):
            counter[str(row["canonical_name"])] += 1
    if not counter:
        if (
            conn is not None
            and cluster_row_indices is not None
            and vectors is not None
            and len(fallback_rows) >= 3
        ):
            ent = _cluster_name_from_entity_centroid(conn, cluster_row_indices, vectors)
            if ent:
                return ent
        return _cluster_name_from_rows(fallback_rows)
    chosen = [name for name, count in counter.most_common(5) if count >= 2]
    if not chosen:
        chosen = [name for name, _ in counter.most_common(2)]
    if not chosen:
        if (
            conn is not None
            and cluster_row_indices is not None
            and vectors is not None
            and len(fallback_rows) >= 3
        ):
            ent = _cluster_name_from_entity_centroid(conn, cluster_row_indices, vectors)
            if ent:
                return ent
        return _cluster_name_from_rows(fallback_rows)
    return {
        "name": " / ".join(chosen[:2]),
        "terms": chosen[:5],
        "size": len(fallback_rows),
    }


def _cluster_name_from_rows(rows: list[sqlite3.Row]) -> dict[str, object]:
    phrases: Counter[str] = Counter()
    labels: Counter[str] = Counter()
    for row in rows:
        for value in (row["section_title"], row["document_title"]):
            label = str(value or "").strip()
            if label and len(label) <= 90:
                if classify_entity_type(label, "heading") == "structure":
                    continue
                nk = normalize_key(label)
                if nk in _VIZ_LABEL_STOP_NORMALIZED:
                    continue
                labels[label] += 1
        text = str(row["text"] or "")
        for match in _VIZ_CAPITALIZED_PHRASE.finditer(text):
            phrase = " ".join(match.group(1).split())
            if classify_entity_type(phrase, "heading") == "structure":
                continue
            nk = normalize_key(phrase)
            if nk in _VIZ_LABEL_STOP_NORMALIZED:
                continue
            phrases[phrase] += 1

    chosen = [phrase for phrase, count in phrases.most_common(3) if count >= 2]
    if not chosen:
        chosen = [label for label, _ in labels.most_common(2)]
    if not chosen:
        chosen = ["Mixed notes"]
    return {"name": " / ".join(chosen[:2]), "terms": chosen[:5], "size": len(rows)}


def _cluster_full_d(normalized: Any) -> tuple[list[int], bool]:
    """Cluster normalized embeddings in full dimensionality.

    Tries HDBSCAN (density-based, auto-k, emits -1 for noise). Falls back to
    MiniBatchKMeans on the full-D vectors when HDBSCAN is unavailable or
    produces fewer than two non-noise clusters.
    """
    n = len(normalized)
    if n == 0:
        return [], False
    if n == 1:
        return [0], False

    expected = max(5, min(20, int(round(n ** 0.5))))

    try:
        import hdbscan

        # Use 'leaf' selection so the hierarchy is cut low — it produces many
        # fine-grained clusters that match what users expect from a topic map.
        # 'eom' (excess of mass) tends to merge almost everything into 1-2 groups
        # for semantic embeddings.
        min_cluster_size = max(3, min(12, int(round(n ** 0.3))))
        min_cluster_size = min(min_cluster_size, max(2, n // 3))
        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=min_cluster_size,
            min_samples=max(1, min_cluster_size // 2),
            metric="euclidean",
            cluster_selection_method="leaf",
        )
        labels = [int(x) for x in clusterer.fit_predict(normalized)]
        unique = set(labels)
        non_noise = unique - {-1}
        # Only accept HDBSCAN when it produces a reasonable number of clusters
        # relative to the expected ~sqrt(N). Otherwise KMeans below gives a
        # more useful map at the cost of hard boundaries.
        if len(non_noise) >= max(4, expected // 2):
            return labels, -1 in unique
    except ImportError:
        pass
    except Exception:
        pass

    from sklearn.cluster import MiniBatchKMeans

    n_clusters = min(expected, n)
    kmeans = MiniBatchKMeans(n_clusters=n_clusters, random_state=42, n_init=3)
    labels = [int(x) for x in kmeans.fit_predict(normalized)]
    return labels, False


def _project_3d(normalized: Any, raw_vectors: Any) -> tuple[Any, str, list[float]]:
    """Project embeddings to 3D for rendering.

    Prefers UMAP (cosine metric, much better separation of semantic clusters)
    and falls back to PCA when UMAP is missing or fails.
    """
    import numpy as np

    n = len(normalized)
    try:
        import umap  # type: ignore[import-not-found]

        n_neighbors = max(2, min(15, n - 1))
        reducer = umap.UMAP(
            n_components=3,
            metric="cosine",
            n_neighbors=n_neighbors,
            min_dist=0.1,
            random_state=42,
        )
        projected = np.asarray(reducer.fit_transform(normalized), dtype=np.float32)
        if projected.ndim == 1:
            projected = projected.reshape(-1, 1)
        return projected, "umap", []
    except ImportError:
        pass
    except Exception:
        pass

    from sklearn.decomposition import PCA

    n_components = min(3, raw_vectors.shape[0], raw_vectors.shape[1])
    pca = PCA(n_components=n_components)
    projected = pca.fit_transform(raw_vectors).astype(np.float32)
    return projected, "pca", pca.explained_variance_ratio_.tolist()


def _remap_cluster_ids(raw_ids: list[int]) -> tuple[list[int], int | None]:
    """Renumber cluster ids to a contiguous 0..k-1 range; noise (-1) goes last."""
    uniques = sorted({int(x) for x in raw_ids})
    non_noise = [c for c in uniques if c != -1]
    mapping: dict[int, int] = {orig: idx for idx, orig in enumerate(non_noise)}
    noise_cluster_id: int | None = None
    if -1 in uniques:
        noise_cluster_id = len(non_noise)
        mapping[-1] = noise_cluster_id
    remapped = [mapping[int(x)] for x in raw_ids]
    return remapped, noise_cluster_id


def _assign_superclusters(
    cluster_centroids: Any,
    proper_cluster_ids: list[int],
    noise_cluster_id: int | None,
) -> tuple[dict[int, int], int]:
    """Group proper clusters into superclusters via agglomerative cosine clustering.

    Returns a mapping from cluster_id -> supercluster_id and the total
    supercluster count. The noise cluster (if any) gets its own trailing id.
    Returns an empty mapping when there are fewer than four proper clusters —
    superclusters only add signal once there are enough groups to collapse.
    """
    import math

    import numpy as np

    n_proper = len(proper_cluster_ids)
    if n_proper < 4:
        return {}, 0

    n_super = max(2, min(max(2, n_proper // 3), int(math.ceil(math.sqrt(n_proper)))))
    n_super = min(n_super, n_proper)

    try:
        from sklearn.cluster import AgglomerativeClustering

        centroids_array = np.asarray(cluster_centroids, dtype=np.float32)
        clusterer = AgglomerativeClustering(
            n_clusters=n_super,
            metric="cosine",
            linkage="average",
        )
        raw = clusterer.fit_predict(centroids_array)
    except Exception:
        return {}, 0

    mapping: dict[int, int] = {}
    for cluster_id, super_id in zip(proper_cluster_ids, raw, strict=False):
        mapping[int(cluster_id)] = int(super_id)

    total = n_super
    if noise_cluster_id is not None:
        mapping[int(noise_cluster_id)] = total
        total += 1
    return mapping, total


def _cluster_distinctive_labels(
    chunk_ids: list[int],
    by_chunk: dict[int, list[sqlite3.Row]],
    corpus_counter: Counter[str],
    total_mentions: int,
    fallback_rows: list[sqlite3.Row],
    *,
    conn: sqlite3.Connection | None = None,
    cluster_row_indices: list[int] | None = None,
    vectors: Any | None = None,
) -> dict[str, object]:
    """Label a cluster by *distinctive* concepts (lift over corpus share)."""
    import math

    cluster_counter: Counter[str] = Counter()
    for cid in chunk_ids:
        for row in by_chunk.get(cid, []):
            cluster_counter[str(row["canonical_name"])] += 1

    total_in_cluster = sum(cluster_counter.values())
    # Require repeats in larger clusters (noise filter) but allow singletons
    # when the cluster only has 1-2 chunks — wikilink dedupe makes counts small.
    min_count = 2 if len(fallback_rows) >= 3 else 1
    scored: list[tuple[float, float, int, str]] = []
    if total_in_cluster > 0 and total_mentions > 0:
        for name, count in cluster_counter.items():
            if count < min_count:
                continue
            in_share = count / total_in_cluster
            corpus_count = corpus_counter.get(name, count)
            corpus_share = corpus_count / total_mentions
            if corpus_share <= 0:
                continue
            lift = in_share / corpus_share
            score = lift * math.log(1 + count)
            scored.append((score, lift, count, name))

    scored.sort(key=lambda item: (-item[0], -item[2], item[3]))
    if scored:
        chosen = [name for (_, _, _, name) in scored][:5]
        return {
            "name": " / ".join(chosen[:2]),
            "terms": chosen,
            "size": len(fallback_rows),
        }

    if (
        conn is not None
        and cluster_row_indices is not None
        and vectors is not None
        and len(fallback_rows) >= 3
    ):
        ent = _cluster_name_from_entity_centroid(conn, cluster_row_indices, vectors)
        if ent:
            return ent

    return _cluster_name_from_rows(fallback_rows)


def _build_superclusters_payload(
    *,
    cluster_state: list[dict[str, Any]],
    super_by_cluster: dict[int, int],
    n_superclusters: int,
    rows: list[sqlite3.Row],
    cluster_ids: list[int],
    projected: Any,
    concept_by_chunk: dict[int, list[sqlite3.Row]],
    corpus_counter: Counter[str],
    total_mentions: int,
    noise_cluster_id: int | None,
) -> list[dict[str, object]]:
    """Aggregate child clusters into superclusters with labels and 3D anchors."""
    if not super_by_cluster or n_superclusters == 0:
        return []

    by_super: dict[int, list[dict[str, Any]]] = {}
    for state in cluster_state:
        cid = int(state["cluster_id"])
        sid = super_by_cluster.get(cid)
        if sid is None:
            continue
        by_super.setdefault(int(sid), []).append(state)

    payload: list[dict[str, object]] = []
    for super_id in sorted(by_super.keys()):
        member_states = by_super[super_id]
        is_noise = all(bool(s["is_noise"]) for s in member_states)

        member_cluster_ids = sorted(int(s["cluster_id"]) for s in member_states)
        all_member_indices: list[int] = []
        for s in member_states:
            all_member_indices.extend(int(i) for i in s["member_indices"])
        member_rows = [rows[i] for i in all_member_indices]
        member_chunk_ids = [int(r["id"]) for r in member_rows]

        if all_member_indices:
            coords = projected[all_member_indices]
            center = [
                float(coords[:, 0].mean()),
                float(coords[:, 1].mean()),
                float(coords[:, 2].mean()) if coords.shape[1] > 2 else 0.0,
            ]
        else:
            center = [0.0, 0.0, 0.0]

        if is_noise:
            name = "Unclassified"
            terms: list[str] = []
        else:
            label = _cluster_distinctive_labels(
                member_chunk_ids,
                concept_by_chunk,
                corpus_counter,
                total_mentions,
                member_rows,
            )
            name = str(label.get("name") or f"Group {super_id + 1}")
            terms_value = label.get("terms")
            terms = [str(t) for t in terms_value] if isinstance(terms_value, list) else []

        payload.append(
            {
                "id": super_id,
                "name": name,
                "size": len(all_member_indices),
                "cluster_ids": member_cluster_ids,
                "terms": terms,
                "center": center,
                "is_noise": is_noise,
            }
        )
    return payload


def _compute_viz_data(conn: sqlite3.Connection) -> dict[str, object]:
    try:
        import numpy as np
        from sklearn.neighbors import NearestNeighbors
    except ImportError as exc:
        raise APIError(
            "missing_dependency",
            "numpy and scikit-learn are required. Run: pip install numpy scikit-learn",
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
        ) from exc

    rows = conn.execute("""
        SELECT
            c.id,
            c.text,
            c.section_title,
            d.id AS document_id,
            d.source_path,
            d.title AS document_title,
            e.vector_json
        FROM chunks c
        JOIN documents d ON c.document_id = d.id
        JOIN embeddings e ON e.chunk_id = c.id
        ORDER BY d.title, c.chunk_index
    """).fetchall()

    if not rows:
        return {
            "points": [],
            "edges": [],
            "n_clusters": 0,
            "clusters": [],
            "variance_explained": [],
            "projection": "none",
        }

    chunk_ids = [int(r["id"]) for r in rows]
    concept_by_chunk = _load_chunk_concept_mentions(conn, chunk_ids)

    vectors = np.array([json.loads(r["vector_json"]) for r in rows], dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    normalized = (vectors / norms).astype(np.float32)

    raw_cluster_ids, _hdbscan_noise = _cluster_full_d(normalized)
    cluster_ids, noise_cluster_id = _remap_cluster_ids(raw_cluster_ids)
    n_clusters = len(set(cluster_ids)) if cluster_ids else 0

    projected, projection_kind, variance_explained = _project_3d(normalized, vectors)

    scale = float(np.abs(projected).max()) if projected.size else 0.0
    if scale > 0:
        projected = projected / scale

    while projected.shape[1] < 3:
        projected = np.column_stack([projected, np.zeros(len(projected), dtype=np.float32)])

    # kNN edges in full-D cosine space — edges now reflect semantic similarity.
    edge_set: set[tuple[int, int]] = set()
    k_nn = min(3, len(rows) - 1)
    if k_nn >= 1:
        nn = NearestNeighbors(n_neighbors=k_nn + 1, metric="cosine")
        nn.fit(normalized)
        _, indices = nn.kneighbors(normalized)
        for i, neighbors in enumerate(indices):
            for j in neighbors[1:]:
                edge_set.add((min(i, int(j)), max(i, int(j))))

    corpus_counter: Counter[str] = Counter()
    for mentions in concept_by_chunk.values():
        for row in mentions:
            corpus_counter[str(row["canonical_name"])] += 1
    total_mentions = sum(corpus_counter.values())

    points: list[dict[str, object]] = []
    for i, r in enumerate(rows):
        cid = int(r["id"])
        payload: dict[str, object] = {
            "id": r["id"],
            "document_id": r["document_id"],
            "source_path": r["source_path"],
            "x": float(projected[i, 0]),
            "y": float(projected[i, 1]),
            "z": float(projected[i, 2]),
            "cluster_id": cluster_ids[i],
            "document_title": r["document_title"],
            "section_title": r["section_title"],
            "snippet": _truncate(r["text"]),
        }
        top = _viz_top_concept_payload(concept_by_chunk.get(cid, []))
        if top:
            payload["top_concept"] = top
        points.append(payload)

    # First pass: per-cluster state that superclustering also needs.
    cluster_state: list[dict[str, Any]] = []
    proper_cluster_ids: list[int] = []
    proper_centroid_units: list[Any] = []
    for cluster_id in range(n_clusters):
        member_indices = [i for i, x in enumerate(cluster_ids) if x == cluster_id]
        if not member_indices:
            continue
        cluster_vectors = normalized[member_indices]
        centroid = cluster_vectors.mean(axis=0)
        c_norm = float(np.linalg.norm(centroid))
        centroid_unit = centroid / c_norm if c_norm > 0 else centroid

        is_noise = noise_cluster_id is not None and cluster_id == noise_cluster_id
        cluster_state.append(
            {
                "cluster_id": cluster_id,
                "member_indices": member_indices,
                "centroid_unit": centroid_unit,
                "is_noise": is_noise,
            }
        )
        if not is_noise:
            proper_cluster_ids.append(cluster_id)
            proper_centroid_units.append(centroid_unit)

    super_by_cluster, n_superclusters = (
        _assign_superclusters(
            np.asarray(proper_centroid_units, dtype=np.float32)
            if proper_centroid_units
            else np.empty((0, normalized.shape[1]), dtype=np.float32),
            proper_cluster_ids,
            noise_cluster_id,
        )
        if proper_cluster_ids
        else ({}, 0)
    )

    clusters: list[dict[str, object]] = []
    for state in cluster_state:
        cluster_id = int(state["cluster_id"])
        member_indices = state["member_indices"]
        centroid_unit = state["centroid_unit"]
        is_noise = bool(state["is_noise"])
        member_rows = [rows[i] for i in member_indices]
        member_chunk_ids = [int(r["id"]) for r in member_rows]

        cluster_vectors = normalized[member_indices]
        cos_to_centroid = cluster_vectors @ centroid_unit
        coherence = float(cos_to_centroid.mean()) if cos_to_centroid.size else 0.0

        n_reps = min(3, len(member_indices))
        rep_local = np.argsort(-cos_to_centroid)[:n_reps].tolist()
        representatives = []
        for li in rep_local:
            r = member_rows[int(li)]
            representatives.append(
                {
                    "chunk_id": int(r["id"]),
                    "document_title": str(r["document_title"] or ""),
                    "snippet": _truncate(r["text"]),
                }
            )

        doc_counter: Counter[int] = Counter()
        doc_titles: dict[int, str] = {}
        for r in member_rows:
            did = int(r["document_id"])
            doc_counter[did] += 1
            doc_titles[did] = str(r["document_title"] or "")
        top_documents = [
            {"document_id": did, "title": doc_titles[did], "count": count}
            for did, count in doc_counter.most_common(5)
        ]

        label = _cluster_distinctive_labels(
            member_chunk_ids,
            concept_by_chunk,
            corpus_counter,
            total_mentions,
            member_rows,
            conn=conn,
            cluster_row_indices=member_indices,
            vectors=vectors,
        )
        name = "Unclassified" if is_noise else str(label.get("name") or f"Cluster {cluster_id + 1}")
        terms_value = label.get("terms")
        terms = [str(t) for t in terms_value] if isinstance(terms_value, list) else []

        super_id = super_by_cluster.get(cluster_id)
        clusters.append(
            {
                "id": cluster_id,
                "name": name,
                "size": len(member_indices),
                "terms": terms,
                "top_documents": top_documents,
                "representatives": representatives,
                "coherence": round(coherence, 4),
                "is_noise": is_noise,
                "supercluster_id": super_id,
            }
        )

    superclusters = _build_superclusters_payload(
        cluster_state=cluster_state,
        super_by_cluster=super_by_cluster,
        n_superclusters=n_superclusters,
        rows=rows,
        cluster_ids=cluster_ids,
        projected=projected,
        concept_by_chunk=concept_by_chunk,
        corpus_counter=corpus_counter,
        total_mentions=total_mentions,
        noise_cluster_id=noise_cluster_id,
    )

    return {
        "points": points,
        "edges": [list(e) for e in sorted(edge_set)],
        "n_clusters": n_clusters,
        "clusters": clusters,
        "superclusters": superclusters,
        "n_superclusters": len(superclusters),
        "variance_explained": variance_explained,
        "projection": projection_kind,
    }


def _success_payload(payload: dict[str, object]) -> dict[str, object]:
    return {"ok": True, **payload}


def _error_payload(error: APIError) -> dict[str, object]:
    return {
        "ok": False,
        "error": {
            "code": error.code,
            "message": error.message,
            "details": error.details,
        },
    }


def _read_bool(payload: dict[str, Any], key: str, default: bool) -> bool:
    value = payload.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise APIError(
        "invalid_boolean",
        f"{key} must be a boolean.",
        status=HTTPStatus.BAD_REQUEST,
        details={"field": key},
    )


def _read_bool_query(query: dict[str, list[str]], key: str, default: bool) -> bool:
    values = query.get(key)
    if not values:
        return default
    return _read_bool({key: values[0]}, key, default)


def _read_top_k(value: object, default: int) -> int:
    if value is None:
        return default
    try:
        top_k = int(value)
    except (TypeError, ValueError) as exc:
        raise APIError(
            "invalid_top_k",
            "top_k must be an integer.",
            status=HTTPStatus.BAD_REQUEST,
            details={"field": "top_k"},
        ) from exc
    if top_k < 1:
        raise APIError(
            "invalid_top_k",
            "top_k must be greater than zero.",
            status=HTTPStatus.BAD_REQUEST,
            details={"field": "top_k"},
        )
    return top_k


def _resolve_provider(settings: Settings, provider_value: object) -> str:
    provider = normalize_provider_name(str(provider_value or settings.llm_provider)) or settings.llm_provider
    if not settings.is_supported_provider(provider):
        raise APIError(
            "invalid_provider",
            f"Unsupported provider: {provider}",
            status=HTTPStatus.BAD_REQUEST,
            details={"provider": provider},
        )
    return provider


def _validate_provider_request(settings: Settings, provider: str, *, require_provider: bool) -> None:
    if not require_provider:
        return
    availability = settings.provider_availability().get(provider, {"available": False, "reason": "Provider is unavailable."})
    if not bool(availability.get("available")):
        raise APIError(
            "provider_unavailable",
            str(availability.get("reason") or f"{provider} is unavailable."),
            status=HTTPStatus.BAD_REQUEST,
            details={"provider": provider},
        )


def _parse_csv_filter(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        items = [item.strip().lower() for item in value.split(",")]
        return tuple(item for item in items if item)
    if isinstance(value, list):
        items = []
        for item in value:
            items.extend(part.strip().lower() for part in str(item).split(","))
        return tuple(item for item in items if item)
    raise APIError("invalid_filter", "Filter values must be strings or arrays.", status=HTTPStatus.BAD_REQUEST)


def _parse_optional_string_filter(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise APIError(
            "invalid_filter",
            f"{field} must be a string.",
            status=HTTPStatus.BAD_REQUEST,
            details={"field": field},
        )
    return value.strip() or None


def _resolve_path_prefix_filter(path_prefix: str | None, settings: Settings) -> str | None:
    if not path_prefix:
        return None
    expanded = Path(path_prefix).expanduser()
    if expanded.is_absolute():
        return str(expanded)
    if settings.vault_path is None:
        return path_prefix.strip()
    return str((settings.vault_path / path_prefix).expanduser().resolve())


def _parse_date_filter(value: object, *, field: str, end_of_day: bool = False) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise APIError(
            "invalid_filter",
            f"{field} must be a date string.",
            status=HTTPStatus.BAD_REQUEST,
            details={"field": field},
        )
    raw = value.strip()
    if not raw:
        return None
    try:
        if len(raw) == 10:
            parsed_date = date.fromisoformat(raw)
            parsed_datetime = datetime.combine(parsed_date, time.max if end_of_day else time.min, tzinfo=timezone.utc)
        else:
            parsed_datetime = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed_datetime.tzinfo is None:
                parsed_datetime = parsed_datetime.replace(tzinfo=timezone.utc)
            else:
                parsed_datetime = parsed_datetime.astimezone(timezone.utc)
    except ValueError as exc:
        raise APIError(
            "invalid_filter",
            f"{field} must be an ISO date or datetime.",
            status=HTTPStatus.BAD_REQUEST,
            details={"field": field},
        ) from exc
    return parsed_datetime.replace(microsecond=0).isoformat()


def _read_filters(payload: dict[str, Any], settings: Settings) -> SearchFilters:
    raw_filters = payload.get("filters", {})
    if raw_filters is None:
        raw_filters = {}
    if not isinstance(raw_filters, dict):
        raise APIError("invalid_filter", "filters must be an object.", status=HTTPStatus.BAD_REQUEST)
    date_from = _parse_date_filter(raw_filters.get("date_from"), field="filters.date_from")
    date_to = _parse_date_filter(raw_filters.get("date_to"), field="filters.date_to", end_of_day=True)
    if date_from and date_to and date_from > date_to:
        raise APIError(
            "invalid_filter",
            "filters.date_from must be before filters.date_to.",
            status=HTTPStatus.BAD_REQUEST,
            details={"field": "filters.date_from"},
        )
    return SearchFilters(
        tags=_parse_csv_filter(raw_filters.get("tags")),
        aliases=_parse_csv_filter(raw_filters.get("aliases")),
        path_prefix=_resolve_path_prefix_filter(
            _parse_optional_string_filter(raw_filters.get("path_prefix"), field="filters.path_prefix"),
            settings,
        ),
        date_from=date_from,
        date_to=date_to,
    )


def _read_filters_from_query(path: str, settings: Settings) -> SearchFilters:
    parsed = urlparse(path)
    query = parse_qs(parsed.query)
    date_from = _parse_date_filter(query.get("date_from", [""])[0], field="date_from")
    date_to = _parse_date_filter(query.get("date_to", [""])[0], field="date_to", end_of_day=True)
    if date_from and date_to and date_from > date_to:
        raise APIError(
            "invalid_filter",
            "date_from must be before date_to.",
            status=HTTPStatus.BAD_REQUEST,
            details={"field": "date_from"},
        )
    return SearchFilters(
        tags=_parse_csv_filter(query.get("tags", [])),
        aliases=_parse_csv_filter(query.get("aliases", [])),
        path_prefix=_resolve_path_prefix_filter(
            _parse_optional_string_filter(query.get("path_prefix", [""])[0], field="path_prefix"),
            settings,
        ),
        date_from=date_from,
        date_to=date_to,
    )


def _serialize_filters(filters: SearchFilters) -> dict[str, object]:
    return {
        "tags": list(filters.tags),
        "aliases": list(filters.aliases),
        "path_prefix": filters.path_prefix,
        "date_from": filters.date_from,
        "date_to": filters.date_to,
    }


def _vault_relative_path(source_path: str, settings: Settings) -> str:
    if settings.vault_path is None:
        return source_path
    try:
        return Path(source_path).expanduser().resolve().relative_to(settings.vault_path.resolve()).as_posix()
    except ValueError:
        return source_path


def handle_api_get(
    path: str,
    settings: Settings,
    refresh_state: RefreshState,
    with_connection,
) -> tuple[HTTPStatus, dict[str, object]]:
    parsed = urlparse(path)
    if parsed.path == "/api/status":
        summary = with_connection(lambda conn: status_summary(conn))
        summary["vault_path"] = str(settings.vault_path) if settings.vault_path else None
        summary["refresh_available"] = settings.vault_path is not None
        summary["refresh_state"] = refresh_state.snapshot()
        summary["llm_provider"] = settings.llm_provider
        summary["default_llm_provider"] = settings.llm_provider
        summary["fallback_llm_provider"] = settings.fallback_llm_provider
        summary["provider_defaults"] = settings.synthesis_model_defaults()
        summary["provider_availability"] = settings.provider_availability()
        summary["llm_provider_order"] = list(settings.ordered_llm_providers())
        summary["supported_llm_providers"] = supported_llm_providers_list()
        summary["enable_reranking"] = settings.enable_reranking
        summary["enable_concept_boost"] = settings.enable_concept_boost
        summary["top_k"] = settings.top_k
        summary["config_diagnostics"] = settings.validate()
        return HTTPStatus.OK, _success_payload(summary)
    if parsed.path == "/api/viz":
        data = with_connection(lambda conn: _compute_viz_data(conn))
        return HTTPStatus.OK, _success_payload(data)
    if parsed.path == "/api/concepts":
        query_params = parse_qs(parsed.query)
        search = query_params.get("search", [""])[0].strip() or None
        entity_type_raw = query_params.get("type", ["concept"])[0].strip().lower()
        if entity_type_raw not in {"concept", "structure", "all"}:
            raise APIError(
                "invalid_concept_type",
                "type must be one of concept, structure, or all.",
                status=HTTPStatus.BAD_REQUEST,
                details={"field": "type"},
            )
        entity_type = None if entity_type_raw == "all" else entity_type_raw
        method = query_params.get("method", [""])[0].strip() or None
        quality = query_params.get("quality", [""])[0].strip().lower() or None
        if quality and quality not in CONCEPT_QUALITIES:
            raise APIError(
                "invalid_concept_quality",
                "quality must be one of strong, medium, weak, or all.",
                status=HTTPStatus.BAD_REQUEST,
                details={"field": "quality"},
            )
        limit = _read_top_k(query_params.get("limit", ["50"])[0], 50)
        offset_raw = query_params.get("offset", ["0"])[0]
        try:
            offset = max(0, int(offset_raw))
        except (TypeError, ValueError) as exc:
            raise APIError(
                "invalid_offset",
                "offset must be a non-negative integer.",
                status=HTTPStatus.BAD_REQUEST,
                details={"field": "offset"},
            ) from exc
        concepts = with_connection(
            lambda conn: list_concepts(
                conn,
                search=search,
                entity_type=entity_type,
                method=method,
                quality=quality,
                limit=limit,
                offset=offset,
            )
        )
        return HTTPStatus.OK, _success_payload(
            {
                "concepts": concepts,
                "count": len(concepts),
                "search": search,
                "type": entity_type_raw,
                "method": method,
                "quality": quality,
                "limit": limit,
                "offset": offset,
            }
        )
    if parsed.path.rstrip("/") == "/api/concepts/search":
        query_params = parse_qs(parsed.query)
        raw_q = query_params.get("q", query_params.get("query", [""]))[0].strip()
        top_k = _read_top_k(query_params.get("top_k", ["20"])[0], 20)
        if not raw_q:
            return HTTPStatus.OK, _success_payload({"query": "", "top_k": top_k, "concepts": []})
        ranked = with_connection(
            lambda conn: semantic_concept_search(conn, raw_q, settings, top_k=top_k)
        )
        return HTTPStatus.OK, _success_payload(
            {"query": raw_q, "top_k": top_k, "concepts": ranked}
        )
    if parsed.path.rstrip("/") == "/api/documents":
        def _list_documents(connection: sqlite3.Connection) -> list[dict[str, object]]:
            rows = connection.execute(
                """
                SELECT d.id, d.title, d.source_path, d.last_modified,
                       COUNT(c.id) AS chunk_count
                FROM documents d
                LEFT JOIN chunks c ON c.document_id = d.id
                GROUP BY d.id
                ORDER BY d.title COLLATE NOCASE
                """,
            ).fetchall()
            return [
                {
                    "document_id": int(r["id"]),
                    "title": str(r["title"]),
                    "source_path": str(r["source_path"]),
                    "vault_relative_path": _vault_relative_path(str(r["source_path"]), settings),
                    "last_modified": str(r["last_modified"]),
                    "chunk_count": int(r["chunk_count"]),
                }
                for r in rows
            ]

        documents = with_connection(_list_documents)
        return HTTPStatus.OK, _success_payload(
            {
                "documents": documents,
                "count": len(documents),
                "vault_path": str(settings.vault_path) if settings.vault_path else None,
            }
        )
    if parsed.path.rstrip("/") == "/api/concepts/graph":
        query_params = parse_qs(parsed.query)
        try:
            limit = max(10, min(500, int(query_params.get("limit", ["200"])[0])))
        except (TypeError, ValueError):
            limit = 200
        try:
            min_cooc = max(1, int(query_params.get("min_cooccurrence", ["2"])[0]))
        except (TypeError, ValueError):
            min_cooc = 2
        try:
            edge_limit = max(50, min(5000, int(query_params.get("edge_limit", ["1000"])[0])))
        except (TypeError, ValueError):
            edge_limit = 1000

        def _concept_graph(connection: sqlite3.Connection) -> dict[str, object]:
            nodes_rows = connection.execute(
                """
                SELECT id, canonical_name, entity_type, mention_count
                FROM entities
                WHERE COALESCE(entity_type, 'concept') != 'structure'
                  AND mention_count > 0
                ORDER BY mention_count DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            nodes = [
                {
                    "id": int(r["id"]),
                    "canonical_name": str(r["canonical_name"]),
                    "entity_type": (str(r["entity_type"]) if r["entity_type"] is not None else "concept"),
                    "mention_count": int(r["mention_count"]),
                }
                for r in nodes_rows
            ]
            if not nodes:
                return {"nodes": [], "edges": [], "limit": limit, "min_cooccurrence": min_cooc}
            ids = tuple(n["id"] for n in nodes)
            placeholders = ",".join("?" for _ in ids)
            edges_rows = connection.execute(
                f"""
                SELECT m1.entity_id AS a, m2.entity_id AS b,
                       COUNT(DISTINCT m1.chunk_id) AS weight
                FROM entity_mentions m1
                JOIN entity_mentions m2
                  ON m1.chunk_id = m2.chunk_id
                 AND m1.entity_id < m2.entity_id
                WHERE m1.entity_id IN ({placeholders})
                  AND m2.entity_id IN ({placeholders})
                GROUP BY m1.entity_id, m2.entity_id
                HAVING weight >= ?
                ORDER BY weight DESC
                LIMIT ?
                """,
                (*ids, *ids, min_cooc, edge_limit),
            ).fetchall()
            edges = [
                {"a": int(r["a"]), "b": int(r["b"]), "weight": int(r["weight"])}
                for r in edges_rows
            ]
            return {
                "nodes": nodes, "edges": edges,
                "limit": limit, "min_cooccurrence": min_cooc, "edge_limit": edge_limit,
            }

        payload = with_connection(_concept_graph)
        return HTTPStatus.OK, _success_payload(payload)
    if parsed.path.startswith("/api/documents/"):
        suffix = parsed.path[len("/api/documents/") :].strip("/")
        if not suffix:
            raise APIError("not_found", "Not found", status=HTTPStatus.NOT_FOUND)
        try:
            document_id = int(suffix)
        except ValueError as exc:
            raise APIError(
                "invalid_document_id",
                "document id must be an integer.",
                status=HTTPStatus.BAD_REQUEST,
                details={"field": "document_id"},
            ) from exc

        def _load_document(connection: sqlite3.Connection) -> dict[str, object] | None:
            row = connection.execute(
                "SELECT id, source_path, title, raw_text FROM documents WHERE id = ?",
                (document_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "document_id": int(row["id"]),
                "source_path": str(row["source_path"]),
                "vault_relative_path": _vault_relative_path(str(row["source_path"]), settings),
                "title": str(row["title"]),
                "raw_text": str(row["raw_text"]),
            }

        document = with_connection(_load_document)
        if document is None:
            raise APIError(
                "document_not_found",
                f"Document {document_id} was not found.",
                status=HTTPStatus.NOT_FOUND,
                details={"document_id": document_id},
            )
        return HTTPStatus.OK, _success_payload(document)
    if parsed.path.startswith("/api/concepts/"):
        suffix = parsed.path[len("/api/concepts/"):].strip("/")
        if not suffix:
            raise APIError("not_found", "Not found", status=HTTPStatus.NOT_FOUND)
        try:
            concept_id = int(suffix)
        except ValueError as exc:
            raise APIError(
                "invalid_concept_id",
                "concept id must be an integer.",
                status=HTTPStatus.BAD_REQUEST,
                details={"field": "concept_id"},
            ) from exc
        detail = with_connection(lambda conn: get_concept_detail(conn, concept_id))
        if detail is None:
            raise APIError(
                "concept_not_found",
                f"Concept {concept_id} was not found.",
                status=HTTPStatus.NOT_FOUND,
                details={"concept_id": concept_id},
            )
        return HTTPStatus.OK, _success_payload(detail)
    if parsed.path == "/api/search":
        query_params = parse_qs(parsed.query)
        query = query_params.get("query", [""])[0].strip()
        top_k = _read_top_k(query_params.get("top_k", [settings.top_k])[0], settings.top_k)
        use_rerank = _read_bool_query(query_params, "rerank", settings.enable_reranking)
        use_concept_boost = _read_bool_query(query_params, "concept_boost", settings.enable_concept_boost)
        debug_scores = _read_bool_query(query_params, "debug_scores", False)
        filters = _read_filters_from_query(path, settings)
        if not query:
            return HTTPStatus.OK, _success_payload({"results": []})
        results = with_connection(
            lambda conn: [
                asdict(item)
                for item in hybrid_search(
                    conn,
                    query,
                    settings,
                    top_k=top_k,
                    filters=filters,
                    use_rerank=use_rerank,
                    use_concept_boost=use_concept_boost,
                    debug_scores=debug_scores,
                )
            ]
        )
        return HTTPStatus.OK, _success_payload(
            {
                "results": results,
                "filters": _serialize_filters(filters),
                "rerank": use_rerank,
                "concept_boost": use_concept_boost,
                "debug_scores": debug_scores,
            }
        )
    raise APIError("not_found", "Not found", status=HTTPStatus.NOT_FOUND)


def handle_api_post(
    path: str,
    payload: dict[str, Any],
    settings: Settings,
    refresh_state: RefreshState,
    with_connection,
) -> tuple[HTTPStatus, dict[str, object]]:
    parsed = urlparse(path)
    if parsed.path == "/api/refresh":
        if settings.vault_path is None:
            raise APIError(
                "vault_not_configured",
                "VAULT_PATH is not configured, so the index cannot be refreshed.",
                status=HTTPStatus.BAD_REQUEST,
            )
        refresh_state.begin()
        try:
            summary = with_connection(
                lambda conn: {
                    **ingest_vault(conn, settings.vault_path, settings),
                    "concepts": refresh_concepts(conn, settings),
                }
            )
        except Exception as exc:
            refresh_state.finish({"status": "failed", "error": str(exc)})
            raise APIError(
                "refresh_failed",
                f"Refresh failed: {exc}",
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
                details={"refresh_state": refresh_state.snapshot()},
            ) from exc
        refresh_state.finish(dict(summary))
        return HTTPStatus.OK, _success_payload(summary)
    if parsed.path == "/api/concepts/refresh":
        result = with_connection(lambda conn: refresh_concepts(conn, settings))
        return HTTPStatus.OK, _success_payload(result)
    if parsed.path == "/api/eval/retrieval":
        raw_cases = payload.get("cases", [])
        if isinstance(raw_cases, dict):
            raw_cases = raw_cases.get("cases", [])
        if not isinstance(raw_cases, list):
            raise APIError(
                "invalid_eval_cases",
                "cases must be a list or an object with a cases list.",
                status=HTTPStatus.BAD_REQUEST,
                details={"field": "cases"},
            )
        cases = [case for case in raw_cases if isinstance(case, dict)]
        top_k_value = _read_top_k(payload.get("top_k"), settings.top_k)
        use_rerank = _read_bool(payload, "rerank", settings.enable_reranking)
        use_concept_boost = _read_bool(payload, "concept_boost", settings.enable_concept_boost)
        result = with_connection(
            lambda conn: evaluate_retrieval_cases(
                conn,
                settings,
                cases,
                top_k=top_k_value,
                use_rerank=use_rerank,
                use_concept_boost=use_concept_boost,
            )
        )
        result["rerank"] = use_rerank
        result["concept_boost"] = use_concept_boost
        return HTTPStatus.OK, _success_payload(result)
    if parsed.path != "/api/chat":
        raise APIError("not_found", "Not found", status=HTTPStatus.NOT_FOUND)

    query = str(payload.get("query", "")).strip()
    if not query:
        raise APIError(
            "missing_query",
            "query is required",
            status=HTTPStatus.BAD_REQUEST,
            details={"field": "query"},
        )

    top_k_value = _read_top_k(payload.get("top_k"), settings.top_k)
    provider = _resolve_provider(settings, payload.get("provider", settings.llm_provider))
    model = str(payload.get("model", "")).strip() or None
    use_llm = _read_bool(payload, "use_llm", settings.enable_llm_synthesis)
    use_query_rewrite = _read_bool(payload, "rewrite_query", settings.enable_query_rewrite)
    use_rerank = _read_bool(payload, "rerank", settings.enable_reranking)
    use_concept_boost = _read_bool(payload, "concept_boost", settings.enable_concept_boost)
    filters = _read_filters(payload, settings)

    request_settings = replace(settings, llm_provider=provider, synthesis_model_name=model)
    _validate_provider_request(request_settings, provider, require_provider=use_llm or use_query_rewrite)

    response = with_connection(
        lambda conn: answer_question(
            conn,
            query,
            request_settings,
            top_k=top_k_value,
            use_llm=use_llm,
            use_query_rewrite=use_query_rewrite,
            use_rerank=use_rerank,
            use_concept_boost=use_concept_boost,
            filters=filters,
        )
    )
    response["filters"] = _serialize_filters(filters)
    response["rerank"] = use_rerank
    response["concept_boost"] = use_concept_boost
    return HTTPStatus.OK, _success_payload(response)


def build_handler(settings: Settings, refresh_state: RefreshState | None = None) -> type[BaseHTTPRequestHandler]:
    refresh_state = refresh_state or RefreshState()

    class Handler(BaseHTTPRequestHandler):
        server_version = "PersonalMemoryHTTP/0.1"

        def do_GET(self) -> None:  # noqa: N802
            try:
                parsed = urlparse(self.path)
                if parsed.path == "/":
                    self._send_asset("index.html")
                    return
                if parsed.path == "/viz":
                    self.send_response(HTTPStatus.FOUND)
                    self.send_header("Location", "/#/map")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if parsed.path in ("/favicon.svg", "/favicon.ico"):
                    self._send_asset("favicon.svg")
                    return
                if parsed.path.startswith("/static/"):
                    rel = parsed.path[len("/static/"):]
                    self._send_asset(rel)
                    return
                status, response = handle_api_get(self.path, settings, refresh_state, self._with_connection)
                self._send_json(response, status=status)
            except APIError as exc:
                self._send_json(_error_payload(exc), status=exc.status)
            except Exception as exc:
                self._send_json(
                    _error_payload(
                        APIError(
                            "internal_error",
                            str(exc),
                            status=HTTPStatus.INTERNAL_SERVER_ERROR,
                        )
                    ),
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )

        def do_POST(self) -> None:  # noqa: N802
            try:
                payload = self._read_json_body()
                status, response = handle_api_post(self.path, payload, settings, refresh_state, self._with_connection)
                self._send_json(response, status=status)
            except APIError as exc:
                self._send_json(_error_payload(exc), status=exc.status)
            except Exception as exc:
                self._send_json(
                    _error_payload(
                        APIError(
                            "internal_error",
                            str(exc),
                            status=HTTPStatus.INTERNAL_SERVER_ERROR,
                        )
                    ),
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _with_connection(self, callback):
            connection = connect(settings.database_path)
            try:
                init_db(connection)
                return callback(connection)
            finally:
                connection.close()

        def _read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(body.decode("utf-8") or "{}")
            except json.JSONDecodeError as exc:
                raise APIError("invalid_json", "Request body must be valid JSON.", status=HTTPStatus.BAD_REQUEST) from exc
            return payload if isinstance(payload, dict) else {}

        def _send_asset(self, name: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            candidate = _resolve_static(name)
            if candidate is None:
                self._send_json(
                    _error_payload(
                        APIError(
                            "not_found",
                            f"Static asset not found: {name}",
                            status=HTTPStatus.NOT_FOUND,
                        )
                    ),
                    status=HTTPStatus.NOT_FOUND,
                )
                return
            payload = candidate.read_bytes()
            content_type = STATIC_CONTENT_TYPES[candidate.suffix.lower()]
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            encoded = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return Handler


def serve_web(settings: Settings, host: str = "0.0.0.0", port: int = 8100) -> None:
    with ThreadingHTTPServer((host, port), build_handler(settings)) as server:
        if host == "0.0.0.0":
            print(
                "Serving Personal Memory on all interfaces "
                f"(local: http://127.0.0.1:{port}, LAN: http://<your-lan-ip>:{port})"
            )
        else:
            print(f"Serving Personal Memory on http://{host}:{port}")
        server.serve_forever()
