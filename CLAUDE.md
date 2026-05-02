# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install
pip install -e .           # development install
pip install -e .[dev]      # with pytest

# Test
pytest                     # all tests
pytest tests/test_parser.py  # single file

# CLI (after install)
personal-memory init-db
personal-memory ingest [--vault PATH]
personal-memory reindex [--vault PATH]
personal-memory embeddings rebuild [--no-breadcrumbs]
personal-memory vectors rebuild
personal-memory concepts reclassify
personal-memory concepts search --query "..."
personal-memory search --query "..." [--concept-boost] [--debug-scores]
personal-memory ask --query "..." [--use-llm]
personal-memory web [--host HOST] [--port PORT]

# Docker
docker compose up --build
```

## Architecture

This is a local-first personal knowledge system that indexes Obsidian Markdown vaults into SQLite and serves hybrid search + LLM-grounded QA via CLI and a web UI.

### Data flow

**Ingestion** (`app/ingest/register.py` orchestrates):
1. Scan vault for `.md` files (`app/vault/scanner.py`)
2. Parse YAML frontmatter, infer titles, extract tags/aliases (`app/vault/obsidian_parser.py`)
3. Skip unchanged files via content hash (`app/util/hashing.py`)
4. Chunk text with heading awareness (`app/processing/chunker.py`)
5. Generate embeddings per chunk (`app/processing/embeddings.py` — sentence-transformer or hash fallback; optional heading breadcrumbs via `USE_BREADCRUMB_EMBEDDINGS`)
6. Write to SQLite FTS5 + embeddings tables (and to `chunk_vectors` when `sqlite-vec` is installed and loads successfully)

**Search** (`app/retrieval/hybrid_search.py`):
1. Optional LLM query rewrite (`app/retrieval/query_rewrite.py`)
2. Parallel FTS5 keyword search + embedding cosine similarity
3. Weighted merge (semantic 0.7, keyword 0.3 by default)
4. Optional reranking (`app/retrieval/rerank.py`)

**QA** (`app/retrieval/qa.py`):
1. Same retrieval as search
2. If `use_llm`: retrieved snippets sent to configured provider via `app/retrieval/llm.py`
3. LLM synthesizes a grounded answer with inline citations; falls back to extractive output

### Key structural decisions

- **No web framework**: `app/web.py` uses stdlib `ThreadingHTTPServer` with a `RefreshState` lock for concurrent refresh operations
- **SQLite is authoritative**: `app/schema.sql` defines the core tables (including FTS5); `app/db.py` runs idempotent migrations (`schema_meta`, missing columns, `entity_embeddings`, lazy `chunk_vectors` with sqlite-vec)
- **Rebuilding**: changing chunking or breadcrumb embedding policy requires `personal-memory embeddings rebuild`. The ANN table `chunk_vectors` is derivative JSON; refresh it with `personal-memory vectors rebuild` after backups or extension install. `personal-memory reindex` rebuilds chunks and FTS from notes but does not require a separate FTS rebuild command today.
- **Models** (`app/models.py`): `ParsedDocument`, `ChunkRecord`, `RetrievalResult`, `SearchFilters` are the main dataclasses passed between layers
- **Multi-provider LLM** (`app/retrieval/llm.py`): supports Ollama, MLX-LM, OpenAI, Gemini, NVIDIA — provider/model selected per-request in the web UI or via config
- **Config hierarchy** (`app/config.py`): JSON config file → environment variables → hardcoded defaults. Docker uses `config_docker.json` as the template.

### Web UI

Static assets live in `app/web_assets/`, organized as ES modules served from `/static/<rel>` (no build step). The single shell document `index.html` mounts a hash-routed app with five views: Chat, Search, Map, Graph, Docs.

Module layout:

```
app/web_assets/
  index.html               # shell (loads tokens/base/shell/components CSS + shell/main.js)
  styles/                  # tokens, base, shell, components, map (loaded lazily by map view)
  lib/                     # api.js, store.js, h.js, format.js, storage.js
  shell/                   # main.js (entry), router.js, nav.js, status-bar.js
  components/              # filters, retrieval-controls, evidence-card, popovers
  views/                   # chat.js, search.js, map.js, graph.js, docs.js
  three/                   # scene, points, edges, labels, palette (used by views/map.js)
```

Key conventions:
- All cross-view state (route, query, filters, selectedDocumentId, selectedConceptId) lives in the tiny `lib/store.js` pub/sub.
- Components consume CSS custom properties from `styles/tokens.css`; no hard-coded colors.
- `views/map.js` lazy-loads `styles/map.css` on first mount; Three.js + addons resolve via the importmap in `index.html`.

REST endpoints (served by `app/web.py`):
- `GET /api/status`, `POST /api/refresh`, `GET /api/refresh-status`
- `GET /api/search?query=...&top_k=...` (filters via repeated `tags`/`aliases` params, plus `path_prefix`/`date_from`/`date_to`)
- `POST /api/chat`
- `GET /api/concepts?...`, `GET /api/concepts/search?q=...`, `GET /api/concepts/<id>`
- `GET /api/concepts/graph?limit=&min_cooccurrence=&edge_limit=` — concept co-occurrence graph for the 2D Graph view
- `GET /api/documents` — vault listing for the Docs view; `GET /api/documents/<id>` — full text
- `GET /api/viz` — 3D projection + clusters + superclusters (consumed by the Map view)
- `POST /api/eval/retrieval`

Static handler: `app/web.py` serves any file under `app/web_assets/` via `/static/<rel>` with traversal protection and a content-type allowlist (see `_resolve_static`). The legacy `/viz` URL 302-redirects to `/#/map`.

The Map view's data pipeline in `app/web.py::_compute_viz_data`:

- **Clustering** runs in the *full* embedding space via HDBSCAN (`hdbscan`) with a `min_cluster_size` scaled to corpus size; noise points (label `-1`) are surfaced as an "Unclassified" cluster. Falls back to `MiniBatchKMeans` on full-D vectors when `hdbscan` is unavailable or finds a single group.
- **3D projection** prefers UMAP (`umap-learn`, cosine metric) and falls back to PCA when UMAP is missing. The payload exposes `"projection": "umap" | "pca"`.
- **Edges** are nearest neighbors in the full-D cosine space (not the 3D projection), so connections reflect semantic similarity. The Map view also offers a client-computed 3D-NN edge mode (visually cleaner) and an off mode.
- **Cluster labels** use *lift* (in-cluster share / corpus share) over `entity_mentions.canonical_name` so names highlight terms that stand out rather than ones that are merely frequent. Each cluster payload includes `terms`, `top_documents`, `representatives` (chunks nearest to the cluster centroid), `coherence`, and `is_noise` for the UI inspection panel. Requires `umap-learn` and `hdbscan` (already declared in `pyproject.toml`).
- **Superclusters** group proper clusters into higher-level themes by running agglomerative clustering (cosine, average linkage) over the full-D cluster centroids. Triggered when there are at least four non-noise clusters; the number is `max(2, min(n//3, ceil(sqrt(n))))`. Each cluster gets a `supercluster_id`, and the payload also includes a top-level `superclusters` array with `{id, name, size, cluster_ids, terms, center: [x,y,z], is_noise}`. The 3D `center` is the mean of member chunks' projected positions and drives floating HTML overlay labels rendered by `three/labels.js`.

### Tests

`tests/conftest.py` provides `fixture_vault`, `settings`, and `connection` fixtures. `tests/fixtures/vault/` has sample Markdown for integration tests. `tests/test_integration.py` runs end-to-end workflows.
