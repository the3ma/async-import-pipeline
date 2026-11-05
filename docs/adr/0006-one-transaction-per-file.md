# ADR-0006: One transaction per file

**Status:** accepted

## Context
A partially imported file is worse than a failed one, because the user has to work out what landed.

## Decision
Validate every row first and report all errors together. Then write all records in one transaction. Upsert on a unique SKU, in sorted order. The production original used `SERIALIZABLE` isolation. A unique constraint with `ON CONFLICT` gives the same safety without retry handling.

## Consequences
- A failed file writes nothing, and reruns are safe.
- One bad row rejects the file, but the user sees every problem at once.
- Sorted writes stop two imports that share SKUs from deadlocking.
