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
mkdir -p data/vault
personal-memory init-db
personal-memory ingest
personal-memory search --query "topic"
personal-memory ask --query "What do my notes say about topic?"
personal-memory web
```

Then open `http://127.0.0.1:8000` in your browser locally, or `http://<your-lan-ip>:8000` from another device on your LAN.

## Configuration

The app now defaults to a repo-local `config.json` file. Edit that file before running the app:

```json
{
  "VAULT_PATH": "./data/vault",
  "DATABASE_PATH": "./data/cache/memory.sqlite3",
  "EMBEDDING_MODEL_NAME": "sentence-transformers/all-MiniLM-L6-v2",
  "TOP_K": 5,
  "ENABLE_LLM_SYNTHESIS": false,
  "ENABLE_QUERY_REWRITE": false,
  "LLM_PROVIDER": "ollama",
  "SYNTHESIS_MODEL_NAME": "gemma3",
  "OPENAI_API_KEY": null,
  "OPENAI_BASE_URL": "https://api.openai.com/v1",
  "GEMINI_API_KEY": null,
  "GEMINI_BASE_URL": "https://generativelanguage.googleapis.com/v1beta",
  "OLLAMA_BASE_URL": "http://localhost:11434/api"
}
```

By default the repo expects your notes at `./data/vault` and stores SQLite data at `./data/cache/memory.sqlite3`.

You can still override any value with environment variables when needed:

- `VAULT_PATH`
- `DATABASE_PATH`
- `EMBEDDING_MODEL_NAME`
- `TOP_K`
- `ENABLE_LLM_SYNTHESIS`
- `ENABLE_QUERY_REWRITE`
- `LLM_PROVIDER`
- `SYNTHESIS_MODEL_NAME`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `GEMINI_API_KEY`
- `GEMINI_BASE_URL`
- `OLLAMA_BASE_URL`

Defaults keep the system local-only. LLM synthesis is disabled in V1.

## Docker Compose

This repo includes a Compose setup similar to the one in `../../tasks`.

Build and start the web app:

```bash
docker compose up --build
# or
docker-compose up --build
```

Run in the background:

```bash
docker compose up -d
# or
docker-compose up -d
```

Stop:

```bash
docker compose down
# or
docker-compose down
```

The web UI is available at `http://localhost:8000`.

Compose mounts:

- `./app` into the container for code changes
- `./data` for the SQLite database and local vault directory
- `./config.json` as the runtime configuration file

If your Obsidian vault lives somewhere else, either:

- edit `VAULT_PATH` in `config.json`
- or replace `./data/vault` with a symlink to your real vault

## Optional LLM Synthesis

`ask` can optionally synthesize a cleaner answer from the retrieved evidence while keeping sources attached.

Recommended local setup with Ollama:

```bash
export ENABLE_LLM_SYNTHESIS=true
export LLM_PROVIDER=ollama
export SYNTHESIS_MODEL_NAME=gemma3
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

## Optional Query Rewriting

Query rewriting is a separate feature from answer synthesis.

- Without it, retrieval uses your original query exactly.
- With it, the configured LLM provider rewrites your natural-language question into a tighter retrieval query first.
- The final response includes `retrieval_query` so you can compare what was actually used.

CLI examples:

```bash
# Old behavior
personal-memory search --query "what did I write about local models?"

# New behavior
personal-memory search --query "what did I write about local models?" --rewrite-query

# Combine rewrite + synthesized answer
personal-memory ask --query "what did I write about local models?" --rewrite-query --use-llm
```

Provider-specific configuration:

```bash
# Ollama
export LLM_PROVIDER=ollama
export OLLAMA_BASE_URL=http://localhost:11434/api
export SYNTHESIS_MODEL_NAME=gemma3

# Gemini
export LLM_PROVIDER=gemini
export GEMINI_API_KEY=your_gemini_key
export SYNTHESIS_MODEL_NAME=gemini-2.5-flash

# OpenAI
export LLM_PROVIDER=openai
export OPENAI_API_KEY=your_openai_key
export SYNTHESIS_MODEL_NAME=gpt-5-mini
```

## Web Chat

The web UI is a thin local wrapper around the existing backend. It exposes:

- `GET /` for the browser chat page
- `GET /api/status` for index stats
- `GET /api/search?query=...` for hybrid search
- `POST /api/chat` for evidence-backed answers

Run it with:

```bash
personal-memory web --host 0.0.0.0 --port 8000
```

The chat page now includes:

- an `Ollama` / `Gemini` / `OpenAI` provider selector
- a `Use LLM synthesis for answers` toggle
- a `Rewrite natural-language query before retrieval` toggle

Those controls apply per request. If the selected provider is unavailable or unconfigured, the app falls back to the original retrieval path and shows the warning in the sidebar.
