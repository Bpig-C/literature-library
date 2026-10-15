# Bounded Concurrency Design: Ingest / Parse / Asset Persistence (Issue #7)

Status: **Design Draft** — for review; no code changes proposed yet.

## Problem

The current producer pipeline serializes ALL ingest/parse operations behind a
single global `.producer.lock`, and the HTTP write gate wraps each request in
an authority `write_guard` with `timeout=0`. A batch of 22 files takes
~22× individual parse time. Different sources cannot proceed in parallel.

## Observed Constraints (from issue #7 + code review)

1. `file_lock(lock_path(service))` — single lock for the entire catalog;
   `parse_source` holds it for the full prepare→parse→package→upload→register
   cycle (~30-120s per source)
2. `trigger_production` iterates sources synchronously within one request
3. `file_lock` default timeout 30s → `busy` error, but authority `write_guard`
   uses `timeout=0` → immediate 409 for concurrent HTTP writes
4. `busy` mapping to HTTP is inconsistent: authority 409 vs parse-trigger
   returning 200 with per-item failed status

## Proposed Design

### Phase 1: Per-Source Locking (backward-compatible, low risk)

Replace the single `.producer.lock` with a per-source lock file:
```
.producer-{source_file_id}.lock
```

- `parse_source(source_id)` acquires only its own source's lock
- Different sources can parse concurrently (bounded by a configurable semaphore)
- Same source still fully serialized (immutable version chain preserved)
- `trigger_production` can dispatch sources to a thread pool

Concurrency limit: `LITLIB_PARSE_CONCURRENCY` env var (default 1 for
backward compat; production recommendation 2-4 based on CPU/RAM).

### Phase 2: Unified Busy Contract

Standardize all lock-conflict responses:

| Layer | Current | Proposed |
|---|---|---|
| authority write_guard | 409 immediate | 409 with `Retry-After` header + JSON body `{"code":"busy","detail":"...","retry_after":N}` |
| producer file_lock | `StorageError('busy')` after 30s | Same 409 + Retry-After |
| parse trigger per-item | 200 with `failed` status | Unchanged (batch result), but each item carries `{"code":"busy"}` for retry |

Client guidance: on 409 busy, wait `Retry-After` seconds, retry same
operation ID (idempotent by design).

### Phase 3: Asynchronous Batch Queue (future)

For very large batches (>50 files):
- `POST /api/parse/trigger` returns `202 Accepted` with a batch job ID
- Client polls `GET /api/parse/jobs?batch_id=X` for progress
- Server-side worker pool processes at bounded concurrency
- Each item retains individual retry/resume semantics

This requires a durable job queue table; defer until Phase 1+2 are
validated with real concurrent load.

## Implementation Estimate

| Phase | Scope | Est. Lines | Risk |
|---|---|---|---|
| Phase 1 | producers.py lock refactor + semaphore | ~80 | Low |
| Phase 2 | authority.py + remote_access.py + parse.py | ~60 | Medium |
| Phase 3 | New batch queue + async handler | ~200 | Higher |

## What Does NOT Change

- Immutable storage mode and SHA-addressed object integrity
- Authority epoch chain and write_guard (still enforced per request)
- Version chain per source (still serialized within a source)
- Client retry semantics (same operation ID)
- Read operations (already concurrent, no lock)

## Open Questions (for user decision)

1. Default concurrency limit: 1 (safe) vs 2 (moderate speedup) vs 4 (aggressive)?
2. Memory budget for concurrent PyMuPDF parsing? (Each instance ~50-200MB)
3. Should Phase 2's `Retry-After` be respected by `litlib_remote.py` automatically?
4. Priority: implement Phase 1 only first, or Phase 1+2 together?
