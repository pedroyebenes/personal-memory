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

from app.config import Settings
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

WEB_ASSET_CONTENT_TYPES = {
    "index.html": "text/html; charset=utf-8",
    "viz.html": "text/html; charset=utf-8",
    "styles.css": "text/css; charset=utf-8",
    "app.js": "application/javascript; charset=utf-8",
}


def _read_web_asset(name: str) -> str:
    asset_path = Path(__file__).with_name("web_assets") / name
    return asset_path.read_text(encoding="utf-8")


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


def _compute_viz_data(conn: sqlite3.Connection) -> dict[str, object]:
    try:
        import numpy as np
        from sklearn.cluster import MiniBatchKMeans
        from sklearn.decomposition import PCA
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
        return {"points": [], "edges": [], "n_clusters": 0, "clusters": [], "variance_explained": []}

    chunk_ids = [int(r["id"]) for r in rows]
    concept_by_chunk = _load_chunk_concept_mentions(conn, chunk_ids)

    vectors = np.array([json.loads(r["vector_json"]) for r in rows], dtype=np.float32)

    # PCA to 3D
    n_components = min(3, vectors.shape[0], vectors.shape[1])
    pca = PCA(n_components=n_components)
    projected = pca.fit_transform(vectors)

    scale = float(np.abs(projected).max())
    if scale > 0:
        projected = projected / scale

    while projected.shape[1] < 3:
        projected = np.column_stack([projected, np.zeros(len(projected), dtype=np.float32)])

    # K-means clusters in 3D PCA space (fast, visually consistent)
    n_clusters = max(5, min(20, int(len(rows) ** 0.5)))
    n_clusters = min(n_clusters, len(rows))
    kmeans = MiniBatchKMeans(n_clusters=n_clusters, random_state=42, n_init=3)
    cluster_ids = kmeans.fit_predict(projected).tolist()

    # Nearest-neighbor edges in 3D PCA space (k=3 per point)
    k_nn = min(3, len(rows) - 1)
    nn = NearestNeighbors(n_neighbors=k_nn + 1, algorithm="ball_tree")
    nn.fit(projected)
    _, indices = nn.kneighbors(projected)

    edge_set: set[tuple[int, int]] = set()
    for i, neighbors in enumerate(indices):
        for j in neighbors[1:]:
            edge_set.add((min(i, int(j)), max(i, int(j))))

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
    cluster_rows: dict[int, list[sqlite3.Row]] = {cluster_id: [] for cluster_id in range(n_clusters)}
    for i, row in enumerate(rows):
        cluster_rows[cluster_ids[i]].append(row)
    clusters = []
    id_to_index = {int(r["id"]): i for i, r in enumerate(rows)}
    for cluster_id in range(n_clusters):
        cluster_row_list = cluster_rows[cluster_id]
        c_ids = [int(r["id"]) for r in cluster_row_list]
        cluster_indices = [id_to_index[cid] for cid in c_ids if cid in id_to_index]
        clusters.append(
            {
                "id": cluster_id,
                **_cluster_name_from_chunk_concepts(
                    c_ids,
                    concept_by_chunk,
                    cluster_row_list,
                    conn=conn,
                    cluster_row_indices=cluster_indices,
                    vectors=vectors,
                ),
            }
        )

    return {
        "points": points,
        "edges": [list(e) for e in edge_set],
        "n_clusters": n_clusters,
        "clusters": clusters,
        "variance_explained": pca.explained_variance_ratio_.tolist(),
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
    provider = str(provider_value or settings.llm_provider).strip().lower() or settings.llm_provider
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
        summary["provider_defaults"] = settings.synthesis_model_defaults()
        summary["provider_availability"] = settings.provider_availability()
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
                    self._send_asset("viz.html")
                    return
                if parsed.path == "/static/styles.css":
                    self._send_asset("styles.css")
                    return
                if parsed.path == "/static/app.js":
                    self._send_asset("app.js")
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
            encoded = _read_web_asset(name).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", WEB_ASSET_CONTENT_TYPES[name])
            self.send_header("Cache-Control", "no-store")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

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


def serve_web(settings: Settings, host: str = "0.0.0.0", port: int = 8000) -> None:
    with ThreadingHTTPServer((host, port), build_handler(settings)) as server:
        if host == "0.0.0.0":
            print(
                "Serving Personal Memory on all interfaces "
                f"(local: http://127.0.0.1:{port}, LAN: http://<your-lan-ip>:{port})"
            )
        else:
            print(f"Serving Personal Memory on http://{host}:{port}")
        server.serve_forever()
