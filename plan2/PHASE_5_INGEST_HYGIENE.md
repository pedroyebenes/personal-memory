# Phase 5: Ingest Hygiene and Migrations

Objective:

- keep incremental ingest trustworthy, make all schema changes idempotent, and expose explicit rebuild commands for every derived layer

## Workstream

Primary workstream:

- targeted entity refresh per document, idempotent migrations in `init_db`, and new rebuild CLI subcommands

## Current Limitation

`_ingest_single_document` in `app/ingest/register.py` re-extracts concepts per file, but `_refresh_entity_mention_counts` and `_prune_orphan_entities` only run at the end of a full vault run (`ingest_vault`, `reindex_vault`, `refresh_concepts`). Per-file ingest can therefore leave stale mention counts and orphaned entities visible to the web UI until the next full run.

Schema changes across Phase 4 (`chunks.heading_path_json`) and Phase 7 (`chunk_vectors`) and Phase 8 (`entity_embeddings`, `entity_vectors`) each require a migration. Today, all schema creation happens through a single `CREATE TABLE IF NOT EXISTS` in `app/schema.sql`, which does not handle new columns on existing tables.

## Tasks

- add `_rebind_entity_counts_for_document(connection, document_id)` in `app/ingest/register.py`:
  - recompute `mention_count` only for entities affected by the document (i.e. entities whose `entity_mentions` touch any `chunk_id` of that document or that had a row deleted in this cycle)
  - delete entities whose `mention_count` drops to zero after the rebind
- invoke `_rebind_entity_counts_for_document` at the end of `_ingest_single_document` when it returned status `indexed`
- add an `_apply_schema_migrations(connection)` helper in `app/db.py::init_db`:
  - `PRAGMA table_info('chunks')` to check for `heading_path_json` and `ALTER TABLE` if missing (Phase 4)
  - `CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors ...` when `sqlite_vec_available` (Phase 7)
  - `CREATE TABLE IF NOT EXISTS entity_embeddings ...` (Phase 8)
  - record the current schema version in a new `schema_meta` table so future migrations can detect and skip completed steps
- new CLI subcommands in `app/cli.py`:
  - `personal-memory embeddings rebuild` — re-encode every chunk's breadcrumb text, replace `embeddings.vector_json` in place, and dual-write `chunk_vectors` when available
  - `personal-memory vectors rebuild` — only populate `chunk_vectors` from existing `embeddings` without re-encoding (already listed in Phase 7, finalized here)
  - `personal-memory concepts reclassify` — already listed in Phase 1, finalized here to apply both the structural tightening and the Phase 3 normalization in one deterministic pass
- update `CLAUDE.md` and `README.md`:
  - document the rebuild commands
  - clarify which phases invalidate stored vectors (Phase 4) versus which are purely derivative (Phase 7, Phase 8)

## Primary Files

- `app/ingest/register.py`
- `app/db.py`
- `app/schema.sql`
- `app/cli.py`
- `CLAUDE.md`
- `README.md`
- `tests/test_ingest.py` (or extended)
- `tests/test_db.py` (new or extended)

## Dependencies

- Finalizes migrations and CLI surfaces introduced in [Phase 1](./PHASE_1_STRUCTURE_FILTER_HARDENING.md), [Phase 4](./PHASE_4_BREADCRUMB_CHUNKS.md), [Phase 7](./PHASE_7_VECTOR_INDEX.md), and [Phase 8](./PHASE_8_ENTITY_EMBEDDINGS.md). Can be split across phases or consolidated here.

## Tests

- per-file ingest: after changing a single note, affected `entities.mention_count` values are correct without running a full `refresh_concepts`
- deleting the only chunk that mentions an entity prunes that entity at the end of the single-document ingest
- `init_db` on an old database (pre-plan-2) adds missing columns/tables and succeeds without data loss
- `embeddings rebuild` reproduces identical top-K results for a fixture query when breadcrumbing is disabled
- `vectors rebuild` is a pure derivative: after running it, `embeddings` rows are unchanged
- `concepts reclassify` is idempotent and preserves `entity_mentions`

## Exit Criteria

- running ingest on a single file leaves the concept layer in a correct, consistent state
- upgrading a pre-plan-2 database requires zero manual SQL
- every derived layer (chunks_fts, embeddings, chunk_vectors once Phase 7 lands, entity_embeddings once Phase 8 lands) has a documented rebuild command
- `CLAUDE.md` and `README.md` describe when to run each rebuild

## Milestone Focus

Milestone:

- Trustworthy Incremental Ingest and Migrations
