# Phase 7: Vector Index

Objective:

- replace the O(N·D) Python cosine scan with a proper ANN index so semantic search scales to vaults with tens of thousands of chunks

## Workstream

Primary workstream:

- optional `sqlite-vec` ANN index that dual-writes alongside the canonical `embeddings.vector_json` column

## Current Limitation

Every semantic query loads all vectors from SQLite and runs cosine similarity in pure Python:

```
# app/retrieval/semantic_search.py
for row in rows:
    semantic_score = cosine_similarity(query_vector, json.loads(row["vector_json"]))
```

For a 10k-chunk, 384-dim vault this is 3.8M float multiplications per query in CPython plus JSON parse overhead; response time grows linearly and dominates overall latency.

## Product Shape

- `sqlite-vec` is loaded at connect time when available; if the extension fails to load (old SQLite, restricted environments, CI default), the app transparently falls back to the current JSON scan
- `embeddings.vector_json` remains the source of truth so rebuilds are always possible
- `chunk_vectors` is a derived ANN index, built once and maintained by ingest

## Tasks

- add dependency `sqlite-vec>=0.1.6` in `pyproject.toml` (install is optional in constrained environments; import is wrapped in a try/except)
- in `app/db.py::connect`:
  - after opening, try `conn.enable_load_extension(True)` + `sqlite_vec.load(conn)`
  - on success, set `conn.sqlite_vec_available = True`; on failure, log once at INFO and set `False`
- in `app/db.py::init_db`:
  - when `sqlite_vec_available`, create `CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors USING vec0(chunk_id INTEGER PRIMARY KEY, embedding float[DIM])` using the configured embedding dimension
  - dimension discovery: read one existing vector from `embeddings` if present; otherwise use a `settings.embedding_dim` (new setting, default 384 for MiniLM)
- in `app/ingest/register.py::_insert_embeddings`:
  - continue writing to `embeddings` unchanged
  - when `chunk_vectors` exists, also `INSERT OR REPLACE INTO chunk_vectors(chunk_id, embedding)` in the same transaction
  - delete-path: when chunks are removed or replaced, delete matching `chunk_vectors` rows
- in `app/retrieval/semantic_search.py`:
  - if `conn.sqlite_vec_available`, run `SELECT chunk_id, distance FROM chunk_vectors WHERE embedding MATCH ? ORDER BY distance LIMIT ?` then join to `chunks`/`documents` for the payload
  - convert `distance` to `semantic_score` with `1 - distance` (cosine) to match existing score semantics
  - otherwise fall back to the current scan
- CLI: `personal-memory vectors rebuild` that iterates existing `embeddings` rows and populates `chunk_vectors` without re-embedding

## Primary Files

- `pyproject.toml`
- `app/db.py`
- `app/schema.sql`
- `app/config.py`
- `app/ingest/register.py`
- `app/retrieval/semantic_search.py`
- `app/cli.py`
- `tests/test_semantic_search.py`

## Dependencies

- Orthogonal to other phases in behavior, but best sequenced after [Phase 4](./PHASE_4_BREADCRUMB_CHUNKS.md) so the first index build covers breadcrumbed vectors.

## Tests

- same top-K chunk IDs on a small fixture with and without the extension loaded (parity guard)
- ANN path gracefully tolerates a missing dimension (new DB with zero chunks)
- dual-write: after ingest, every row in `embeddings` has a matching row in `chunk_vectors` when available
- delete-path: reingesting a changed document prunes stale `chunk_vectors` rows
- `vectors rebuild` is idempotent and does not touch `embeddings`

## Exit Criteria

- semantic search for a 10k-chunk vault runs in sub-100 ms on a dev laptop with the extension loaded
- tests pass in CI where the extension may not be present
- removing the extension at runtime doesn't corrupt data (app simply uses the fallback path)

## Milestone Focus

Milestone:

- Scalable Semantic Retrieval
