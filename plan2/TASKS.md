# Task List

Backlog and phase summary for the Concepts & Retrieval Overhaul. Phases are listed here in execution order and match the file numbering in this folder.

## Priority Summary

Priority order (matches phase numbering):

1. Structural classifier hardening (unblocks cleanup of existing data)
2. Viz concept surface (visible bug fix)
3. Concept normalization & dedup
4. Breadcrumbed chunks + embeddings
5. Ingest hygiene, migrations, rebuild CLI
6. Field-weighted BM25 + exact-concept boost
7. Vector index via `sqlite-vec`
8. Optional entity-level embeddings

## Backlog

### Concept Extraction (Phase 1)

- Extend `_STRUCTURAL_LABEL_PATTERNS` to cover:
  - subtitled chapters (`Capítulo IV: ...`, `Chapter 3 — ...`)
  - front-matter sections (`Prólogo`, `Epílogo`, `Introducción`, `Prefacio`, `Dedicatoria`, `Índice`, `Tabla de Contenidos`, `Glosario`, `Apéndice`, `Nota del Autor`)
  - ordinal forms (`Parte Primera`, `Capítulo Segundo`, `Libro Tercero`)
  - ISO and natural-language dates, weekday/month names
- Apply structural classification to `alias` mentions too.
- Add regression fixtures covering the above.
- Provide a `concepts reclassify` CLI that re-runs classification over existing rows without dropping provenance.

### Visualization (Phase 2)

- Join `entity_mentions` / `entities` in `_compute_viz_data` so every point carries a `top_concept` when available.
- Derive cluster names from concept mentions instead of raw `section_title` / `document_title` counts.
- Drop per-point text labels in `app/web_assets/viz.html`; keep tooltips and the pinned note popover.
- Route tooltip/popover titles through `top_concept.canonical_name` with fallback to `document_title`.
- Update `searchableText()` to stop pulling section titles.

### Concept Normalization (Phase 3)

- Fold Unicode NFKD + strip combining marks in `normalize_key` (so `"México" → "mexico"`).
- Add a conservative trailing-`s`/`es` plural collapse when a base form already exists.
- Add a normalized-key stoplist to protect `find_concepts_for_terms` from stopword-only queries.
- Make `_upsert_entity` merge two previously-distinct entities whose keys now fold to the same value (reassign `entity_mentions`, sum counts, keep the richer `canonical_name`).

### Chunking & Embeddings (Phase 4)

- Track full heading path while chunking; extend `ChunkRecord` with `heading_path: list[str]`.
- Add `chunks.heading_path_json` (idempotent migration in `init_db`).
- Add `breadcrumb_text(document_title, heading_path, chunk_text)` helper.
- Embed the breadcrumbed text instead of raw `chunk.text`; keep `chunks.text` unchanged for display and FTS.
- Stored vectors become stale — they must be refreshed via the Phase 5 rebuild CLI, not automatically.

### Ingest Hygiene (Phase 5)

- Add `_rebind_entity_counts_for_document(document_id)` so per-file ingest no longer leaves stale mention counts.
- Idempotent migrations in `init_db` for `chunks.heading_path_json`, `chunk_vectors`, `entity_embeddings`.
- New CLI subcommands: `embeddings rebuild`, `vectors rebuild`, `concepts reclassify`.
- Update `CLAUDE.md` and `README.md` with rebuild guidance.

### Keyword Retrieval (Phase 6)

- Switch `keyword_search` ordering to `bm25(chunks_fts, 3.0, 5.0, 1.0)` across `document_title`, `section_title`, `text` (no schema change).
- Prefer phrase / `NEAR` clauses in `_build_fts_query` when the user provides multiple alphanumeric tokens.
- Add an exact-normalized-key concept boost in `hybrid_search` that complements the existing `_apply_concept_boost`.

### Vector Index (Phase 7)

- Add `sqlite-vec>=0.1.6` dep with a runtime-loaded fallback to the current JSON path.
- Attempt extension load in `app/db.py`; expose `conn.sqlite_vec_available`.
- Create `chunk_vectors` (`vec0`) virtual table when available; dual-write on ingest.
- Prefer ANN lookup in `semantic_search`; fall back to the Python cosine scan otherwise.
- `personal-memory vectors rebuild` to backfill `chunk_vectors` from existing JSON vectors.

### Entity-Level Embeddings (Phase 8)

- New `entity_embeddings(entity_id, model_name, vector_json, created_at)` table.
- Compute on concept refresh for `entity_type='concept'` with `mention_count >= 2`.
- Expose `/api/concepts/search?q=...` for concept-level semantic search.
- Use as cluster-naming fallback in the viz when the dominant mentions are too sparse.

### Tests & Evaluation (cross-phase)

- Structural pattern coverage (subtitled chapter, Prólogo, ISO date, Parte Primera, weekday).
- Diacritic fold, plural collapse, stoplist protection, `_upsert_entity` merge.
- `heading_path` propagation through chunker and ingest.
- Weighted BM25 prioritizes heading/title hits.
- `sqlite-vec` present vs. absent produce identical top-K on a small fixture.
- `_compute_viz_data` returns `top_concept` only for entity-backed chunks; cluster names derive from concepts.
- Small golden-question regression before/after Phase 6 to catch ranking regressions.

## Implementation Plan

### Phase 1: Structure Filter Hardening

Goal:

- prevent structural labels from entering the `concept` entity type

Tasks:

- extend `_STRUCTURAL_LABEL_PATTERNS` for subtitled chapters, front-matter sections, ordinals, dates, weekdays, months
- apply structural classification to `alias` mentions
- one-shot `concepts reclassify` CLI that reruns classification over existing rows without dropping provenance

Definition of done:

- `Capítulo IV: Donde se cuenta...`, `Prólogo`, `2026-04-20`, `Parte Primera`, `Monday` are all classified as `structure`
- concept-aware boosts no longer fire on these
- existing databases can be upgraded without a full reindex

### Phase 2: Viz Concept Surface

Goal:

- make the 3D embedding visualization show real concepts instead of chapter/section headings

Tasks:

- rewrite `_compute_viz_data` to emit per-chunk `top_concept`
- derive cluster names from `entity_mentions`
- remove point text labels in `viz.html`
- update tooltip/popover/search to use `top_concept`

Definition of done:

- hovering a point in the viz shows a concept from the concept layer when available
- cluster labels are not dominated by chapter names for a book-heavy vault
- the viz no longer renders text labels on individual points

### Phase 3: Concept Normalization

Goal:

- collapse trivial variants into the same entity so downstream boosts and lists are stable

Tasks:

- NFKD fold + combining-mark strip in `normalize_key`
- conservative plural collapse when base form exists
- normalized-key stoplist
- merge logic in `_upsert_entity` for keys that now fold together

Definition of done:

- `México` and `Mexico` resolve to one entity
- `Quijote` and `quijotes` do not fragment into distinct entities when the base form is already known
- refresh is still idempotent after the merge

### Phase 4: Breadcrumbed Chunks

Goal:

- give embeddings and FTS the context they need to disambiguate chunks inside long works

Tasks:

- add `heading_path` to `ChunkRecord`
- add `chunks.heading_path_json` (idempotent migration)
- embed `breadcrumb_text(document_title, heading_path, chunk.text)`
- rely on Phase 5's rebuild CLI since vectors need re-embedding

Definition of done:

- semantic search for "Don Quijote Dulcinea" surfaces chunks from the right book rather than arbitrary chapters
- raw `chunks.text` remains untouched and continues to drive FTS and the UI display

### Phase 5: Ingest Hygiene

Goal:

- make incremental ingest and migrations trustworthy

Tasks:

- `_rebind_entity_counts_for_document` for per-file ingest
- idempotent `init_db` migrations for all new columns/tables
- rebuild CLIs: `embeddings rebuild`, `vectors rebuild`, `concepts reclassify`
- docs update in `CLAUDE.md` and `README.md`

Definition of done:

- running `ingest` on a single changed file never leaves stale mention counts
- upgrading from a pre-plan-2 DB requires zero manual SQL
- every derived layer has a documented rebuild command

### Phase 6: Weighted FTS

Goal:

- heading and title hits outrank incidental body hits in keyword search

Tasks:

- switch `keyword_search` to weighted BM25
- prefer `NEAR` / phrase clauses for multi-token queries
- add an exact-normalized-key concept boost in `hybrid_search`

Definition of done:

- queries that match a heading or alias outrank queries that only match body text
- exact-concept matches produce a reproducible, capped boost surfaced in `score_explanation`
- a small golden-question regression shows equal-or-better top-3 accuracy

### Phase 7: Vector Index

Goal:

- remove the O(N·D) Python cosine scan on every semantic query

Tasks:

- add `sqlite-vec` dep
- load extension in `app/db.py` with feature flag
- create `chunk_vectors` vec0 table when available
- dual-write in `_insert_embeddings`
- ANN-first `semantic_search` with JSON fallback
- `personal-memory vectors rebuild`

Definition of done:

- `semantic_search` is sub-100ms for 10k-chunk vaults on a dev laptop
- tests pass with and without the extension loaded
- existing DBs get a `chunk_vectors` index on first run without re-embedding

### Phase 8: Entity-Level Embeddings

Goal:

- allow concept-level semantic search and give the viz a better cluster-naming fallback

Tasks:

- `entity_embeddings` table and compute path on concept refresh
- `/api/concepts/search?q=...`
- viz cluster naming falls back through entity embeddings when raw mentions are too sparse

Definition of done:

- searching for "fate" finds concepts like `Destiny`, `Fortune`, `Suerte` even when those strings never appear literally
- cluster names remain sensible on a vault with very short chunks

## Recommended Starting Order

Phases are numbered in execution order. Follow them sequentially. Phase 8 is optional and can be deferred without blocking earlier phases.

## Explicitly Deferred

- automatic file watching / background workers
- cross-document concept relation tables
- LLM-assisted entity extraction
- multi-vault support
- major UI redesign
