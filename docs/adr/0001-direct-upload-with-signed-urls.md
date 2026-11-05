# ADR-0001: Direct upload with signed URLs

**Status:** accepted

## Context
Sending files through the API ties a request, a connection and memory to every upload, and the gateway's size and time limits become the limits of the feature.

## Decision
The API creates a job and returns a signed PUT URL for one object, valid for 15 minutes. The browser uploads straight to storage.

## Consequences
- API cost per import does not depend on file size.
- The browser never holds a storage credential.
- A signed PUT cannot cap file size, so size is enforced after upload by the edge validator.
- Storage needs CORS for the app origin.
