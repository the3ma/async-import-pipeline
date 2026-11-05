# ADR-0004: Process pool plus a database sweeper, not a message broker

**Status:** accepted

## Context
Parsing is CPU-bound and must stay off the event loop. Volume is low, and a broker is one more system to run. The production original used an in-memory pool alone, so a restart stranded jobs.

## Decision
Keep a `ProcessPoolExecutor` in the API process, and treat the job row as the durable queue. A sweeper resubmits stale `processing` jobs up to 3 times, recovers `pending` jobs whose file has arrived, and expires the rest. Claims are single atomic `UPDATE`s.

## Consequences
- No broker, and jobs survive restarts.
- Workers are at-least-once, so imports must be idempotent. A row lock and upserts make them so.
- Recovery takes up to one sweep interval plus the stale timeout.
- Workers scale with API replicas. If imports outgrow that, move them to a dedicated worker service.
- A killed worker breaks the pool permanently, so `submit` replaces a broken pool.
