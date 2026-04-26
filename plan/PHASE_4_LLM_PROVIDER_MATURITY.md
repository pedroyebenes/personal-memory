# Phase 4: LLM and Provider Maturity

Objective:

- make provider behavior more configurable, robust, and efficient

## Workstream

Primary workstream:

- LLM and provider maturity

## Tasks

- split rewrite model defaults from synthesis model defaults
- add provider-specific generation settings such as temperature and max output where supported
- add streaming support in the web chat UI and backend
- add request-level caching for rewrites and synthesis where inputs are identical
- add fallback policies for provider failures

## Primary Files

- `app/config.py`
- `app/retrieval/llm.py`
- `app/retrieval/query_rewrite.py`
- `app/web.py`
- provider-related tests

## Dependencies

- Phase 1 for clean error contracts
- Phase 2 for UI affordances around provider/model display

## Deliverables

- separate rewrite and synthesis model defaults
- provider-specific generation controls
- streaming chat support
- request caching
- fallback policies

## Exit Criteria

- rewrite and synthesis can be configured independently
- supported providers can stream responses to the UI
- repeated identical requests avoid unnecessary provider calls
- provider failures degrade gracefully

## Milestone Focus

Milestone:

- Provider Maturity
