# Taking it to production

This repo runs on LocalStack. The original ran on Azure. The pipeline only needs four things from a platform.

| Need | Local | AWS | Azure |
|---|---|---|---|
| Object storage with signed PUT | LocalStack S3 | S3 | Blob Storage, write-only SAS |
| Created event | S3 to SQS | S3 to SQS or EventBridge | Event Grid, or a blob trigger |
| Edge validator | `importer.edge` | Lambda | Azure Function |
| Private route to the webhook | Compose network | VPC | VNet integration, private DNS |

## Checklist

- [ ] Set `IMPORT_SECRET` from a secret store (services refuse to start without it)
- [ ] Put real authentication on `POST /imports`, and tie jobs to users
- [ ] Keep `/webhook/import` off the public gateway
- [ ] Private buckets, with CORS limited to the app origin
- [ ] Lifecycle rule on the entry bucket, and a retention decision for persistent
- [ ] Malware scanning before the worker reads a file
- [ ] Run the parser with limits on memory and time
- [ ] Connection pooling in the API (`psycopg_pool`)
- [ ] Dead-letter queue for storage events
- [ ] Alerts on `All attempts to send result failed`, `WORKER_LOST`, and the age of the oldest open job
- [ ] Raise `SWEEP_SECONDS` and `STALE_SECONDS` above the longest real import
- [ ] Schema migrations instead of `db/schema.sql`

## Lessons from the production original

- **Write back the location when a file moves.** The original had this bug until a later fix: the worker looked in the old container, and local runs could not show it because the file never moved there.
- **Check config names end to end.** Variables named differently in IaC and app fall back silently to defaults. Fail at startup.
- **Always send the correlation ID.** A read failure reporting `filename: "unknown"` can never be matched to a job. Take the name from the trigger.
- **Use bind parameters everywhere,** including internal stores. File metadata is user input.
- **Test recovery with a real kill.** Here, a simulated crash test passed while a real `kill -9` hung every later import, because it broke the process pool for good. A healthy replica then masked the bug until the test ran on a single instance.
