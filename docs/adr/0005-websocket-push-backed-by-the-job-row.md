# ADR-0005: WebSocket push, backed by the job row

**Status:** accepted

## Context
Polling wastes requests on an event that happens a few times per job. The production original kept final messages in process memory, which tied it to one replica and lost results on restart.

## Decision
Push over WebSockets. The job row is the source of truth: subscribing registers first and then reads the row, so late subscribers get the result. Postgres `NOTIFY` fans changes out to every replica. `GET /imports/{id}` covers clients without a socket.

## Consequences
- Any replica can serve any subscriber, with no Redis.
- Delivery can repeat, so clients treat messages as state, not events.
- `NOTIFY` is not durable. A replica that misses one relies on the client's next subscribe.
