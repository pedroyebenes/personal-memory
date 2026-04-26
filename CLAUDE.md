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
personal-memory search --query "..."
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
- **Multi-provider LLM** (`app/retrieval/llm.py`): supports Ollama, OpenAI, Gemini, NVIDIA — provider/model selected per-request in the web UI or via config
- **Config hierarchy** (`app/config.py`): JSON config file → environment variables → hardcoded defaults. Docker uses `config_docker.json` as the template.

### Web UI

Static assets live in `app/web_assets/`. REST endpoints are `/api/status`, `/api/search`, `/api/chat`, `/api/refresh`.

### Tests

`tests/conftest.py` provides `fixture_vault`, `settings`, and `connection` fixtures. `tests/fixtures/vault/` has sample Markdown for integration tests. `tests/test_integration.py` runs end-to-end workflows.
