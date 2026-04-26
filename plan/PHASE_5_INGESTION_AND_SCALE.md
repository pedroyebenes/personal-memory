# Phase 5: Ingestion and Scale

Objective:

- improve performance and resilience for larger vaults without moving to background workers

## Workstream

Primary workstream:

- ingestion and scale improvements

## Tasks

- capture per-file ingest failures and report them in CLI and web responses
- use filesystem metadata in addition to content hashing to reduce expensive reads
- improve frontmatter normalization and validation further
- design and implement multi-vault support or better scoped vault selection
- prepare rebuild semantics that later derived layers can reuse

## Primary Files

- `app/ingest/register.py`
- `app/vault/scanner.py`
- `app/vault/obsidian_parser.py`
- `app/cli.py`
- `app/web.py`
- ingest/integration tests

## Dependencies

- Phase 1 for structured reporting

## Deliverables

- richer ingest diagnostics
- reduced unnecessary file work
- stronger metadata validation
- multi-vault plan or implementation
- clearer rebuild semantics for derived layers

## Exit Criteria

- ingestion surfaces partial failures instead of hiding them
- large vault refreshes do less unnecessary work
- malformed metadata does not stop a refresh

## Milestone Focus

Milestone:

- Scale and Diagnostics
