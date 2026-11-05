# ADR-0007: Signed webhook and per-task tokens

**Status:** accepted

## Context
The production original relied on network placement to protect its webhook, and a task UUID was the only credential for reading a result.

## Decision
The edge signs webhook bodies with HMAC-SHA256. `POST /imports` returns a task token, also an HMAC, which is required to read or subscribe to that job.

## Consequences
- A caller inside the network cannot forge a result.
- A task ID alone reveals nothing.
- Tokens are capabilities, not identity. A real deployment should tie jobs to the signed-in user.
- There is one shared secret to rotate.
