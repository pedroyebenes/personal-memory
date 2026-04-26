# Phase 4: Breadcrumbed Chunks

Objective:

- give the embedding model the document and heading context it needs to disambiguate chunks from long works without changing the raw text stored for display or FTS

## Workstream

Primary workstream:

- heading-path propagation in the chunker and breadcrumb-prefixed embeddings in ingest

## Current Limitation

Chunks today only record the nearest section title:

```
# app/processing/chunker.py
def _build_sections(text: str) -> list[tuple[str | None, str, int]]:
    ...
```

Only the immediate heading survives; the outer H1/H2 context is lost. Semantic search across a long work (e.g. a full book) sees every chapter body without knowing which book or section it belongs to, so retrieval for "Don Quijote and Dulcinea" can get confused between books that share the same surface wording.

## Product Shape

- chunker emits a `heading_path: list[str]` per chunk representing the full ancestor heading chain (H1 → H2 → ...)
- persisted in `chunks.heading_path_json`
- at embed time, the string actually sent to the encoder is:

```
breadcrumb_text = f"{document_title}\n> {' > '.join(heading_path)}\n\n{chunk_text}"
```

- raw `chunks.text` stays untouched, so the UI, snippets, and `chunks_fts` behavior are unchanged
- `chunks_fts.section_title` continues to be the nearest heading

## Tasks

- extend `ChunkRecord` in `app/models.py` with `heading_path: list[str]` (default `[]`)
- rewrite `_build_sections` / `_split_large_section` in `app/processing/chunker.py` to track a stack of active headings by level and attach the current path to every chunk
- add `breadcrumb_text(document_title: str, heading_path: list[str], chunk_text: str) -> str` in `app/processing/chunker.py` (or a small new `app/processing/breadcrumbs.py`)
- idempotent migration in `app/db.py::init_db`: `ALTER TABLE chunks ADD COLUMN heading_path_json TEXT NOT NULL DEFAULT '[]'` (guarded by a `PRAGMA table_info` check)
- update `_insert_chunks` in `app/ingest/register.py` to persist `json.dumps(chunk.heading_path)` into the new column
- update `_insert_embeddings` to encode `breadcrumb_text(...)` instead of `chunk.text`
- leave `semantic_search` and `keyword_search` untouched — they keep reading `chunks.text` and `chunks_fts`; the breadcrumb only shapes the vectors

## Primary Files

- `app/models.py`
- `app/processing/chunker.py`
- `app/ingest/register.py`
- `app/db.py`
- `app/schema.sql`
- `tests/test_chunker.py`

## Dependencies

- Requires rebuild path in [Phase 5](./PHASE_5_INGEST_HYGIENE.md): existing vectors are computed from raw text and must be re-embedded to benefit from the breadcrumb; until `embeddings rebuild` runs, the new column coexists with old vectors without breaking retrieval.
- Plays well with [Phase 7](./PHASE_7_VECTOR_INDEX.md): re-embedding is also a natural time to populate the ANN index.

## Tests

- `chunk_document("# A\n...\n## B\n...\n### C\n...")` returns chunks with `heading_path` of `["A"]`, `["A", "B"]`, `["A", "B", "C"]`
- `breadcrumb_text("Don Quijote", ["Capítulo IV", "Aventura"], "body")` emits the expected two-line header
- raw `chunk.text` is unchanged by breadcrumbing
- ingest persists `heading_path_json` as a JSON array and restores it on read
- a semantic-search sanity fixture: a query mentioning the book title retrieves chunks from that book over a similarly-worded chunk from another document

## Exit Criteria

- `chunks.heading_path_json` is populated for every new or reindexed chunk
- `embeddings rebuild` (from Phase 5) re-encodes the breadcrumb form in place without touching chunks
- semantic retrieval on a multi-book vault improves measurably on a small golden-question set
- no behavior change in FTS or snippets

## Milestone Focus

Milestone:

- Context-Aware Embeddings
