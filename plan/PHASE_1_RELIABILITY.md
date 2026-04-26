# Phase 1: Reliability Baseline

Objective:

- make refresh, search, and chat behavior predictable under failure

## Workstream

Primary workstream:

- reliability and operational safety

## Tasks

- define a shared API error schema for web handlers
- refactor `app/web.py` to use consistent success and error envelopes where appropriate
- add refresh job locking and state reporting
- add provider/config startup validation helpers in `app/config.py`
- add targeted tests for provider unavailability, invalid inputs, refresh collisions, and ingestion exceptions

## Primary Files

- `app/web.py`
- `app/config.py`
- `app/ingest/register.py`
- `tests/test_config.py`
- new web endpoint tests

## Dependencies

- none

## Deliverables

- structured web error responses
- refresh lock / in-progress state
- stronger startup validation
- automated coverage for major failure paths

## Exit Criteria

- no common UI failure path depends on a dropped HTTP connection
- a second refresh request is rejected cleanly while one is already running
- provider/config problems are surfaced in a structured way
- endpoint tests cover the major failure paths

## Recommended First Steps

1. Standardize API error payloads for `status`, `search`, `refresh`, and `chat`.
2. Add refresh-state protection to prevent concurrent refresh runs.
3. Add web endpoint tests covering refresh, search, chat, and provider availability.
