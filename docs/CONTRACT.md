# Contract

## `POST /imports`

Starts an import. The body is optional.

```jsonc
// request
{ "filename": "sheet.pdf" }
// 201
{ "url": "http://storage/entry/<task_id>.pdf?X-Amz-...", "task_id": "<uuid>", "token": "<hex>" }
```

## `PUT <url>`

Sends the raw file to storage. On Azure Blob, also send `x-ms-blob-type: BlockBlob`.

## `GET /imports/{task_id}`

Needs the `X-Import-Token` header. Returns the result object below. A wrong token and an unknown ID both return `404`.

## `WS /ws`

```jsonc
// client to server, once per task, again after every reconnect
{ "action": "subscribe", "task_id": "<uuid>", "token": "<hex>" }
```

The server sends the current state straight away, then every change until the job ends. Messages can repeat. Treat them as state.

## Result object

```jsonc
{
  "task_id": "<uuid>",
  "status": "success",          // pending | processing | success | error
  "error_code": "",
  "message": "",                // human-readable when status is error
  "record_ids": ["<uuid>"],
  "filename": "sheet.pdf",
  "started_at": "2026-01-01T12:00:00+00:00",
  "completed_at": "2026-01-01T12:00:01+00:00"   // null until the job ends
}
```

## `POST /webhook/import`

Internal, from edge to API. `X-Signature` is the HMAC-SHA256 hex digest of the raw body. Keep this route off the public gateway.

```jsonc
// accepted
{ "status": "success", "filename": "<task_id>.pdf", "folder": "persistent" }
// rejected
{ "status": "error", "filename": "<task_id>.pdf", "error_code": "FILE_TOO_LARGE", "message": "..." }
```

Replies `{"status":"accepted"}`, or `{"status":"ignored"}` when the job has already left `pending`. A bad signature gets `401`.

## Error codes

| Code | Raised by | Meaning |
|---|---|---|
| `FILE_TOO_LARGE` | Edge | Above `MAX_FILE_SIZE` |
| `INVALID_FILE_TYPE` | Edge | No `%PDF-` signature |
| `INVALID_CONTENT` | Worker | Rows failed validation. `message` lists each line |
| `IMPORT_FAILED` | Worker | Unreadable PDF, or a storage or database failure |
| `UPLOAD_EXPIRED` | Sweeper | No file arrived in time |
| `WORKER_LOST` | Sweeper | The worker died on every attempt |

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | local | PostgreSQL connection |
| `IMPORT_SECRET` | none, required | Signs webhooks and task tokens |
| `AWS_ENDPOINT` | local | Storage and queue, as seen from services |
| `AWS_PUBLIC_ENDPOINT` | local | Storage, as seen from the browser |
| `ENTRY_BUCKET`, `PERSISTENT_BUCKET` | `entry`, `persistent` | The two storage areas |
| `EVENTS_QUEUE` | `upload-events` | Storage event queue |
| `API_WEBHOOK_URL` | local | Where the edge reports |
| `MAX_FILE_SIZE` | `5120000` | Bytes |
| `SIGNED_URL_TTL` | `900` | Seconds |
| `WORKERS` | `4` | Worker processes per API replica |
| `SWEEP_SECONDS` | `30` | Sweeper interval. Compose uses `2` |
| `STALE_SECONDS` | `120` | Age before recovery. Compose uses `5` |
| `MAX_ATTEMPTS` | `3` | Worker attempts per job |
