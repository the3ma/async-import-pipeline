# ADR-0003: Validate at the edge, before the application

**Status:** accepted

## Context
Junk files should not use a worker slot or reach a PDF parser.

## Decision
A storage-triggered function checks size from the event and the `%PDF-` signature from a 5-byte ranged read. Valid files move to a persistent bucket and rejected files are deleted.

## Consequences
- A rejected file costs a few bytes of reading, not a parse.
- There is one more deployable.
- The signature check proves the type claim only. It is not a malware check.
