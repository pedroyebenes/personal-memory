# Project Overview

This project is a local-first personal memory system designed for a single user with one Obsidian vault as the source of truth.

The V1 goal is to make Markdown notes queryable through a simple CLI while preserving provenance. The system ingests notes into SQLite, normalizes and chunks their content, generates local embeddings, and supports keyword, semantic, and hybrid retrieval. It can also answer questions by returning evidence-backed output built from the most relevant chunks.

## What The Project Does

At a high level, the system turns a folder of Markdown notes into a searchable local knowledge base.

The current implementation does the following:

1. Scans an Obsidian vault recursively for `.md` files.
2. Parses YAML frontmatter when present.
3. Preserves the full original file content as `raw_text`.
4. Produces `normalized_text` with frontmatter removed and line endings normalized.
5. Infers a document title from frontmatter or the filename.
6. Computes a content hash to detect whether a note changed.
7. Stores documents, tags, aliases, chunks, embeddings, and ingestion runs in SQLite.
8. Splits note content into heading-aware chunks.
9. Generates one embedding per chunk using a local sentence-transformer model when available.
10. Supports keyword search through SQLite FTS5.
11. Supports semantic search by embedding the query and comparing it to stored chunk embeddings in Python.
12. Combines keyword and semantic scores into a hybrid ranking.
13. Returns grounded search and question-answering results with source provenance.

## Why It Exists

The project is built around a few practical constraints:

- The data should stay local.
- SQLite should remain the authoritative store.
- Derived artifacts should be reproducible from the source notes.
- Retrieval results should always point back to the exact note chunks they came from.
- The system should be inspectable and easy to debug.

This means the implementation avoids cloud dependencies, vector databases, background workers, and UI complexity in V1.

## Current Architecture

The code is organized into a few clear layers.

### `app/config.py`

Loads runtime settings from environment variables or an optional JSON config file.

Supported settings:

- `VAULT_PATH`
- `DATABASE_PATH`
- `EMBEDDING_MODEL_NAME`
- `TOP_K`
- `ENABLE_LLM_SYNTHESIS`
- `SYNTHESIS_MODEL_NAME`

In V1, LLM synthesis is intentionally disabled by default.

### `app/db.py` and `app/schema.sql`

These files define the SQLite database connection and schema initialization logic.

The schema includes core V1 tables:

- `documents`
- `document_aliases`
- `document_tags`
- `chunks`
- `embeddings`
- `ingestion_runs`

It also includes placeholder tables for future layers:

- `events`
- `entities`
- `entity_mentions`
- `document_summaries`

Those future-facing tables exist so the codebase can grow without changing the basic storage model later.

### `app/vault/`

This layer is responsible for reading the Obsidian vault.

- `scanner.py` finds Markdown files recursively.
- `obsidian_parser.py` parses frontmatter, infers titles, extracts tags and aliases, and normalizes note content.

The parser currently ignores more advanced Obsidian features such as transclusions, task semantics, and Mermaid parsing.

### `app/ingest/`

This layer owns the ingestion pipeline.

Its main responsibilities are:

- decide whether a document changed
- upsert the document row
- refresh tags and aliases
- delete stale chunks and embeddings for changed documents
- regenerate chunks
- regenerate embeddings
- record ingestion runs

The design intentionally prefers full reprocessing of an individual changed document over complex partial updates.

### `app/processing/`

This layer transforms note text into retrieval-ready artifacts.

- `chunker.py` performs heading-aware chunking.
- `embeddings.py` generates vector representations for chunk text.
- `summaries.py` exists as a stub for future derived layers.

Chunking tries to respect note structure by splitting on headings first. If a section is too large, it falls back to paragraph-based splitting with overlap. Small sections can be merged with adjacent chunks so retrieval is less fragmented.

### `app/retrieval/`

This layer implements the search and QA behavior.

- `keyword_search.py` runs FTS5 queries against chunk text and titles.
- `semantic_search.py` compares query embeddings against stored chunk embeddings.
- `hybrid_search.py` merges those two result sets with weighted scoring.
- `qa.py` formats the top evidence into a grounded answer structure.

The answer is currently extractive rather than generative. That is deliberate: V1 prioritizes provenance and predictable behavior over synthesis.

## Database Model

The database is the central system of record.

### Documents

Each Markdown file becomes one row in `documents`.

The row stores:

- source path
- title
- raw text
- normalized text
- frontmatter JSON
- content hash
- timestamps

The content hash is used to skip unchanged files during ingestion.

### Tags and Aliases

Frontmatter tags and aliases are normalized into `document_tags` and `document_aliases`.

This allows them to be queried independently of the raw frontmatter payload and keeps the relational model inspectable.

### Chunks

Each document can have many chunks.

A chunk stores:

- document id
- chunk index
- section title
- text
- token estimate
- character offsets
- creation time

The chunk is the fundamental retrieval unit. Search and QA operate on chunks rather than whole documents.

### Embeddings

Each chunk has one embedding row with:

- the chunk id
- the embedding model name
- the vector as a JSON array
- a creation timestamp

V1 stores vectors directly in SQLite and performs similarity in Python instead of relying on a separate vector store.

### Ingestion Runs

Every ingest or reindex operation creates a row in `ingestion_runs`.

This provides lightweight operational visibility into what happened, when it happened, and how many documents were processed.

## Ingestion Flow

The ingestion pipeline works like this:

1. The user runs `personal-memory ingest --vault PATH`.
2. The system scans the vault for Markdown files.
3. Each file is read and parsed.
4. A content hash is computed from the raw file contents.
5. If the hash matches the stored hash, the file is skipped.
6. If the file is new or changed, the document row is inserted or updated.
7. Existing chunks and embeddings for that document are deleted.
8. New chunks are generated from normalized text.
9. New embeddings are generated for each chunk.
10. FTS rows are refreshed so keyword search stays in sync.

The `reindex` command is more aggressive: it clears all chunks and embeddings and rebuilds them for the whole vault.

## Search Flow

The `search` command uses hybrid retrieval.

Internally, it runs:

1. keyword search through FTS5
2. semantic search through cosine similarity
3. score merge with default weights:
   semantic `0.7`
   keyword `0.3`

Each result includes:

- document title
- source path
- chunk id
- chunk index
- section title
- snippet
- keyword score
- semantic score
- final score

That makes the output inspectable and suitable for downstream tooling.

## Ask Flow

The `ask` command is built on top of hybrid retrieval.

Instead of trying to fabricate a polished answer, V1 gathers the top chunks and formats them as evidence-backed output:

- the original question
- a concise answer section assembled from the best snippets
- structured sources

Each source includes the document title, file path, chunk id, chunk index, section title, and snippet. That is the provenance guarantee for the current version.

## Embedding Behavior

The intended embedding backend is:

- `sentence-transformers/all-MiniLM-L6-v2`

If `sentence-transformers` is unavailable in the runtime environment, the code falls back to a deterministic hash-based embedding function so the pipeline can still execute. That fallback is mainly useful for local development and testing; real semantic quality depends on an actual embedding model being available.

## CLI Commands

The CLI currently supports:

- `init-db`
- `status`
- `ingest --vault PATH`
- `reindex --vault PATH`
- `search --query "..."`
- `ask --query "..."`

### `init-db`

Initializes the SQLite schema.

### `status`

Shows counts for stored documents, chunks, embeddings, and the most recent ingestion run.

### `ingest`

Indexes new or changed notes from the vault.

### `reindex`

Rebuilds chunk and embedding data from scratch for the full vault.

### `search`

Returns ranked retrieval results in structured JSON.

### `ask`

Returns a grounded answer structure with supporting sources.

## What Is Stubbed Or Deferred

Several parts of the broader memory-system design are present only as placeholders in V1:

- episodic/event extraction
- entity extraction and mention linking
- document summaries
- derived reasoning layers
- background automation
- UI
- optional LLM synthesis

The codebase includes schema and module hooks for those areas so they can be added later without rethinking the entire foundation.

## Design Tradeoffs In V1

The project makes a few deliberate tradeoffs:

- SQLite over a more complex storage stack
- per-document reprocessing over partial incremental patching
- inspectable JSON and SQL records over hidden state
- extractive answers over generative synthesis
- local execution over cloud services

These choices reduce complexity and make the system easier to reason about during the first iteration.

## Known Limitations

The current implementation is intentionally narrow.

- Only Markdown files are ingested.
- Obsidian-specific advanced constructs are mostly ignored.
- Semantic similarity runs in Python over stored vectors, which is fine for V1 but will not scale indefinitely.
- Embeddings are only as good as the available local model.
- The answer generation is evidence assembly, not full reasoning or synthesis.
- There is no UI or long-running indexing service.

## Future Direction

The likely next steps after V1 are:

1. improve chunking and note-structure awareness
2. add better handling for wikilinks and Obsidian metadata
3. support richer derived layers such as summaries and entities
4. add optional LLM synthesis while keeping citations mandatory
5. improve ranking and retrieval diagnostics
6. add a UI once the CLI workflow is stable

## Summary

This project is currently a pragmatic local retrieval system for personal notes.

Its main job is to ingest Markdown from an Obsidian vault, transform those notes into structured retrieval units, and answer queries with clear provenance. The implementation is intentionally simple, inspectable, and local-first so the foundation is solid before more advanced memory features are introduced.
