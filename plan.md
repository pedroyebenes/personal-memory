# Design Improvement Plan

Tasks sorted by priority (impact × effort ROI).

- [ ] **1. Ingestion transaction boundaries** — wrap each document's inserts (chunks, embeddings, entity mentions) in a single `BEGIN/COMMIT/ROLLBACK` so failures don't leave orphaned rows. `app/ingest/register.py`
- [ ] **2. Viz computation blocks the server** — move `_compute_viz_data()` to a background thread triggered by refresh; cache the result and serve stale-while-revalidate. `app/web.py`
- [ ] **3. Silent degradation signals** — expose `embedding_mode` and `search_mode` in `/api/status`; show a warning banner in the UI when running with fallback embeddings or O(n) scan. `app/processing/embeddings.py`, `app/retrieval/semantic_search.py`, `app/web.py`, `app/web_assets/`
- [ ] **4. Score normalization** — add a normalization pass after all boosts so `final_score` stays in [0, 1]. `app/retrieval/hybrid_search.py`
- [ ] **5. Connection pooling / init_db per request** — call `init_db()` once at startup and reuse connections instead of opening a fresh connection on every HTTP request. `app/db.py`, `app/web.py`
- [ ] **6. Expose magic scoring constants to config** — move `CONCEPT_BOOST_WEIGHT`, `EXACT_CONCEPT_BOOST_MAX`, rerank `max_boost`, BM25 field weights, and `evidence_sufficiency_threshold` into `Settings` with config-file overrides. `app/config.py`, `app/retrieval/`
- [ ] **7. Chunker offset tracking** — fix `char_start`/`char_end` to account for `"\n\n"` separators, or remove the fields until they can be accurately maintained. `app/processing/chunker.py`
- [ ] **8. LLM provider abstraction** — replace the `if/elif` chain in `_generate_text` with a provider registry and wire `fallback_llm_provider` for automatic failover. `app/retrieval/llm.py`
- [ ] **9. Settings provider field duplication** — replace the 15 per-provider top-level fields with a `dict[str, ProviderConfig]` that mirrors the `PROVIDERS` nested config block. `app/config.py`
- [ ] **10. Decompose web.py** — extract route handlers into `app/api/` modules and move viz computation to `app/retrieval/viz.py`. `app/web.py`
