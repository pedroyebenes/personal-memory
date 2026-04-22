# Personal Memory

Local-first personal memory system for a single Obsidian vault.

## Features

- SQLite as the authoritative store
- Obsidian Markdown ingestion with YAML frontmatter support
- Heading-aware chunking
- Local embeddings with sentence-transformers
- Keyword, semantic, and hybrid retrieval
- Evidence-backed `ask` output with source provenance
- Local web chatbot backed by the same retrieval pipeline

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
personal-memory init-db
personal-memory ingest --vault /path/to/vault
personal-memory search --query "topic"
personal-memory ask --query "What do my notes say about topic?"
personal-memory web
```

Then open `http://127.0.0.1:8000` in your browser.

## Configuration

Configuration can be set with environment variables:

- `VAULT_PATH`
- `DATABASE_PATH`
- `EMBEDDING_MODEL_NAME`
- `TOP_K`
- `ENABLE_LLM_SYNTHESIS`
- `SYNTHESIS_MODEL_NAME`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`

Defaults keep the system local-only. LLM synthesis is disabled in V1.

## Optional LLM Synthesis

`ask` can optionally synthesize a cleaner answer from the retrieved evidence while keeping sources attached.

Set:

```bash
export ENABLE_LLM_SYNTHESIS=true
export OPENAI_API_KEY=...
export SYNTHESIS_MODEL_NAME=gpt-5-mini
```

Then run:

```bash
personal-memory ask --query "What did I decide about retrieval?" --use-llm
```

Behavior:

- the system still retrieves sources locally first
- the LLM only sees the selected snippets
- the answer is expected to cite sources like `[Source 1]`
- if evidence is weak or the API is not configured, the system falls back to extractive output

## Web Chat

The web UI is a thin local wrapper around the existing backend. It exposes:

- `GET /` for the browser chat page
- `GET /api/status` for index stats
- `GET /api/search?query=...` for hybrid search
- `POST /api/chat` for evidence-backed answers

Run it with:

```bash
personal-memory web --host 127.0.0.1 --port 8000
```
