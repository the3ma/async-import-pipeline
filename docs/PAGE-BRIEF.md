# Case-study page brief

How to build a page like the [Async Export Pipeline case study](https://the3ma.github.io/async-export-pipeline/) from this repo. Use the same skeleton: a single column with a sticky table of contents, light and dark themes, and a caption with a one-line takeaway under every diagram.

**Thesis:** Importing user files without carrying a single byte through the API request path.

**Abstract:** Signed uploads, edge validation, a worker pool and WebSocket results: an import pipeline that keeps the API free and the user working.

**Hero block**

| Field | Value |
|---|---|
| Role | Architect & full-stack engineer |
| Scope | Browser upload, storage events, edge validation, workers, push notifications |
| Stack | FastAPI, PostgreSQL, S3 / Azure Blob, Azure Functions, Vue, Docker Compose |
| Status | Generalised from production work, with a runnable reference |

| # | Section | Source |
|---|---|---|
| 1 | Summary | README: Summary |
| 2 | The failures | README: Failures this design removes |
| 3 | Requirements | README: Goals |
| 4 | Who it serves | README: Who it serves |
| 5 | The product | `docs/images/import-tray.png` |
| 6 | Architecture | README: Architecture |
| 7 | Decisions | `docs/adr/` |
| 8 | Implementation | README: How it works |
| 9 | Operations | `docs/CONTRACT.md`, `docs/PRODUCTION.md` |
| 10 | Trade-offs | README: Trade-offs |
| 11 | Results | README: Wins |
| 12 | Try it | README: Quick start |
| 13 | Lessons | `docs/PRODUCTION.md` |
| 14 | What's next | README: Limitations, still open |
| 15 | Contact | Same as the export page: email, LinkedIn, GitHub |

**Footer note:** Generalized from production work: the employer, client and product are not named, and details are changed. Source code under the MIT licence.
