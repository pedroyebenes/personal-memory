# Personal Memory

Local-first personal memory system for a single Obsidian vault.

## Features

- SQLite as the authoritative store
- Obsidian Markdown ingestion with YAML frontmatter support
- Heading-aware chunking
- Local embeddings with sentence-transformers
- Keyword, semantic, and hybrid retrieval
- Metadata/rerank/concept-aware scoring diagnostics
- Deterministic concept extraction with structure/concept separation
- Concept inspection with chunk-level provenance
- Retrieval evaluation against local golden questions
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
personal-memory concepts list
personal-memory eval retrieval
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
  "ENABLE_RERANKING": false,
  "LLM_PROVIDER": "ollama",
  "SYNTHESIS_MODEL_NAME": null,
  "OPENAI_SYNTHESIS_MODEL_NAME": "gpt-5-mini",
  "GEMINI_SYNTHESIS_MODEL_NAME": "gemini-2.5-flash",
  "NVIDIA_SYNTHESIS_MODEL_NAME": "z-ai/glm-4.7",
  "OLLAMA_SYNTHESIS_MODEL_NAME": "gemma3",
  "OPENAI_API_KEY": null,
  "OPENAI_BASE_URL": "https://api.openai.com/v1",
  "GEMINI_API_KEY": null,
  "GEMINI_BASE_URL": "https://generativelanguage.googleapis.com/v1beta",
  "NVIDIA_API_KEY": null,
  "NVIDIA_BASE_URL": "https://integrate.api.nvidia.com/v1",
  "OLLAMA_BASE_URL": "http://localhost:11434/api"
}
```

By default the repo expects your notes at `./data/vault` and stores SQLite data at `./data/cache/memory.sqlite3`.

Path resolution depends on how you run the app:

- When running directly on the host, relative paths in `config.json` are resolved relative to the `config.json` file on the host.
- When running in Docker, `config.json` is read inside the container at `/app/config.json`, so relative paths are resolved relative to `/app` inside the container.
- In Docker Compose, `VAULT_PATH` is overridden to `/vault`, so the container reads from the mounted host vault instead of the repo-relative default.

You can still override any value with environment variables when needed:

- `VAULT_PATH`
- `DATABASE_PATH`
- `EMBEDDING_MODEL_NAME`
- `TOP_K`
- `ENABLE_LLM_SYNTHESIS`
- `ENABLE_QUERY_REWRITE`
- `ENABLE_RERANKING`
- `LLM_PROVIDER`
- `SYNTHESIS_MODEL_NAME`
- `OPENAI_SYNTHESIS_MODEL_NAME`
- `GEMINI_SYNTHESIS_MODEL_NAME`
- `NVIDIA_SYNTHESIS_MODEL_NAME`
- `OLLAMA_SYNTHESIS_MODEL_NAME`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `GEMINI_API_KEY`
- `GEMINI_BASE_URL`
- `NVIDIA_API_KEY`
- `NVIDIA_BASE_URL`
- `OLLAMA_BASE_URL`
- `USE_BREADCRUMB_EMBEDDINGS` (`true` / `false`) — when `true`, chunk embeddings include document title and heading path as context

Defaults keep the system local-only. LLM synthesis and reranking are disabled unless explicitly enabled.

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
- `./data` for the SQLite database
- `${HOST_VAULT_PATH:-./data/vault}` from the host into `/vault` in the container
- `./config_docker.json` as the runtime configuration file

Compose also sets:

- `OLLAMA_BASE_URL=http://host.docker.internal:11434/api` so the container can reach an Ollama server running on your host machine
- `VAULT_PATH=/vault` so the app reads notes from the mounted host vault
- `DATABASE_PATH=/app/data/cache/memory.sqlite3` so the SQLite index persists under `./data`

If your Obsidian vault lives outside the repo on the host, point Compose at it when you start the app:

```bash
HOST_VAULT_PATH="/absolute/path/to/your/vault" docker compose up --build
```

If you do not set `HOST_VAULT_PATH`, Compose falls back to `./data/vault`.

Examples:

```bash
# Use a host vault outside the repo
HOST_VAULT_PATH="$HOME/Documents/Obsidian/MainVault" docker compose up --build

# Use the repo-local sample vault
docker compose up --build
```

If you are not using host Ollama, set `OLLAMA_BASE_URL` to the correct reachable endpoint for your setup.

## Indexing

The SQLite schema is initialized automatically when you run the CLI or web app, but note ingestion is not automatic unless you trigger it.

- `personal-memory ingest` performs incremental indexing
- changed notes are reprocessed
- unchanged notes are skipped
- deleted notes are pruned from the index

Use:

```bash
personal-memory ingest
```

Or specify the vault explicitly:

```bash
personal-memory ingest --vault "/absolute/path/to/your/vault"
```

If you need a full rebuild instead of an incremental refresh, use:

```bash
personal-memory reindex
```

## Rebuilding derived layers

Some SQLite tables are **derived** from your notes and can get out of date when algorithms change:

| Layer | When it goes stale | Command |
| --- | --- | --- |
| Chunk text + FTS (`chunks`, `chunks_fts`) | Edits in the vault | `personal-memory ingest` (incremental) or `personal-memory reindex` (full) |
| Chunk embeddings (`embeddings`) | You change embedding model, toggle breadcrumbs, or chunk boundaries change in code | `personal-memory embeddings rebuild` (optionally `--no-breadcrumbs` to match `USE_BREADCRUMB_EMBEDDINGS=false`) |
| sqlite-vec ANN index (`chunk_vectors`) | After restore, first install of `sqlite-vec`, or if rows drifted | `personal-memory vectors rebuild` (no re-encoding; reads existing `vector_json`) |
| Concept classification / merges (`entities`, `entity_mentions`) | After upgrading concept normalization or structural rules | `personal-memory concepts reclassify` |

Heading **breadcrumbs** affect only what text is sent to the embedder (see `USE_BREADCRUMB_EMBEDDINGS` in `config.json` or the environment). After toggling breadcrumbs or fixing chunking, run `personal-memory embeddings rebuild` so semantic search matches the new policy.

Optional ANN support: `pip install -e '.[vec]'` installs `sqlite-vec`. If the extension does not load, the app keeps using the existing Python cosine scan over `embeddings.vector_json`.

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

## Concepts and Structures

Concept extraction is deterministic and local. Refresh/reindex populates concepts from titles, filenames, headings, tags, aliases, wikilinks, inline tags, emphasis markers, definitions, and repeated body phrases.

Semantic concepts are separate from structural labels such as `CAPÍTULO XL` or date-like note titles:

```bash
personal-memory concepts list
personal-memory concepts list --type structure
personal-memory concepts list --method alias
personal-memory concepts list --quality strong
personal-memory concepts show --name "Project North Star"
personal-memory concepts noise-report
personal-memory concepts refresh
```

Concept details include exact mention provenance, top supporting chunks, related documents, and copyable Markdown source references.

## Retrieval Quality Checks

You can keep a local JSON file of vault-specific retrieval checks and run it without any cloud service:

```json
{
  "cases": [
    {
      "id": "north-star",
      "query": "North Star launch",
      "expected_paths": ["project-note.md"],
      "expected_terms": ["launch"]
    }
  ]
}
```

Run:

```bash
personal-memory eval retrieval --cases retrieval_eval.json
personal-memory eval retrieval --cases retrieval_eval.json --concept-boost --rerank
```

Search and ask results include score explanations, matched concepts, and copyable source references so ranking behavior can be inspected locally.

Provider-specific configuration:

```bash
# Ollama
export LLM_PROVIDER=ollama
export OLLAMA_BASE_URL=http://localhost:11434/api
export OLLAMA_SYNTHESIS_MODEL_NAME=gemma3

# Gemini
export LLM_PROVIDER=gemini
export GEMINI_API_KEY=your_gemini_key
export GEMINI_SYNTHESIS_MODEL_NAME=gemini-2.5-flash

# NVIDIA
export LLM_PROVIDER=nvidia
export NVIDIA_API_KEY=your_nvidia_api_key
export NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
export NVIDIA_SYNTHESIS_MODEL_NAME=z-ai/glm-4.7

# OpenAI
export LLM_PROVIDER=openai
export OPENAI_API_KEY=your_openai_key
export OPENAI_SYNTHESIS_MODEL_NAME=gpt-5-mini
```

## Web Chat

The web UI is a thin local wrapper around the existing backend. It exposes:

- `GET /` for the browser chat page
- `GET /api/status` for index stats
- `GET /api/search?query=...` for hybrid search
- `GET /api/concepts?...` for concept listing and filtering
- `POST /api/refresh` for incremental index refresh
- `POST /api/chat` for evidence-backed answers

Run it with:

```bash
personal-memory web --host 0.0.0.0 --port 8000
```

The chat page now includes:

- an `Ollama` / `Gemini` / `NVIDIA` / `OpenAI` provider selector
- a model textbox next to the provider selector, prefilled from that provider's configured default
- a `Use LLM synthesis for answers` toggle
- a `Rewrite natural-language query before retrieval` toggle
- a `Refresh Index` button that runs incremental ingest against the configured vault path

The `Refresh Index` button runs the same incremental ingest path as `personal-memory ingest`.

Those controls apply per request. If the selected provider is unavailable or unconfigured, the app falls back to the original retrieval path and shows the warning in the sidebar.
