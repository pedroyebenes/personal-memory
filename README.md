# Personal Memory

Local-first personal memory system for a single Obsidian vault.

## Features

- SQLite as the authoritative store
- Obsidian Markdown ingestion with YAML frontmatter support
- Heading-aware chunking
- Local embeddings with sentence-transformers
- Keyword, semantic, and hybrid retrieval
- Evidence-backed `ask` output with source provenance

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
personal-memory init-db
personal-memory ingest --vault /path/to/vault
personal-memory search --query "topic"
personal-memory ask --query "What do my notes say about topic?"
```

## Configuration

Configuration can be set with environment variables:

- `VAULT_PATH`
- `DATABASE_PATH`
- `EMBEDDING_MODEL_NAME`
- `TOP_K`
- `ENABLE_LLM_SYNTHESIS`
- `SYNTHESIS_MODEL_NAME`

Defaults keep the system local-only. LLM synthesis is disabled in V1.
