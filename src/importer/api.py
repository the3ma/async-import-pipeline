"""API: signs uploads, owns job state, runs workers, and pushes results over WebSockets."""

import asyncio
import contextlib
import json
import logging
import uuid
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from datetime import UTC, datetime, timedelta
from multiprocessing import get_context
from pathlib import Path

import psycopg
from botocore.exceptions import ClientError
from fastapi import (
    FastAPI,
    Header,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from importer import common, sample_pdf, worker

log = logging.getLogger("importer.api")
STATIC = Path(__file__).parent / "static"
FINAL = ("success", "error")

subscribers: dict[uuid.UUID, set[WebSocket]] = defaultdict(set)
pool: ProcessPoolExecutor
running: set[asyncio.Future] = set()


def connect():
    # ponytail: one connection per call, add psycopg_pool when request rates matter.
    return psycopg.AsyncConnection.connect(common.DATABASE_URL, row_factory=dict_row)


def new_pool() -> ProcessPoolExecutor:
    return ProcessPoolExecutor(common.WORKERS, mp_context=get_context("spawn"))


def submit(task_id: uuid.UUID) -> None:
    global pool
    loop = asyncio.get_running_loop()
    try:
        future = loop.run_in_executor(pool, worker.run, task_id)
    except BrokenProcessPool:  # a killed worker breaks the pool for good, so replace it
        log.warning("Worker pool broken, replacing it")
        pool = new_pool()
        future = loop.run_in_executor(pool, worker.run, task_id)
    running.add(future)
    future.add_done_callback(finished)


def finished(future: asyncio.Future) -> None:
    running.discard(future)
    if not future.cancelled() and future.exception():
        log.error("Worker died: %s. The sweeper will retry.", future.exception())


async def notify(conn, task_id: uuid.UUID) -> None:
    await conn.execute("SELECT pg_notify(%s, %s)", (common.NOTIFY_CHANNEL, str(task_id)))


def to_result(job: dict) -> dict:
    return {
        "task_id": str(job["task_id"]),
        "status": job["status"],
        "error_code": job["error_code"],
        "message": job["message"],
        "record_ids": [str(record_id) for record_id in job["record_ids"]],
        "filename": job["filename"],
        "started_at": job["created_at"].isoformat(),
        "completed_at": job["modified_at"].isoformat() if job["status"] in FINAL else None,
    }


async def read_job(task_id: uuid.UUID) -> dict | None:
    async with await connect() as conn:
        cursor = await conn.execute("SELECT * FROM imports WHERE task_id = %s", (task_id,))
        return await cursor.fetchone()


async def push(task_id: uuid.UUID) -> None:
    job = await read_job(task_id)
    if job is None:
        return
    for websocket in list(subscribers.get(task_id, ())):
        with contextlib.suppress(Exception):  # a dead socket must not stop the others
            await websocket.send_json(to_result(job))
    if job["status"] in FINAL:
        subscribers.pop(task_id, None)


async def listen() -> None:
    """Postgres NOTIFY fans results out, so any replica can serve any subscriber."""
    while True:
        try:
            conn = await psycopg.AsyncConnection.connect(common.DATABASE_URL, autocommit=True)
            async with conn:
                await conn.execute(f"LISTEN {common.NOTIFY_CHANNEL}")
                async for message in conn.notifies():
                    await push(uuid.UUID(message.payload))
        except Exception:
            log.exception("Listener failed, reconnecting")
            await asyncio.sleep(1)


async def recover_stale(conn) -> None:
    """Jobs whose worker died. Every step is an atomic claim, so replicas cannot double-submit."""
    stale = timedelta(seconds=common.STALE_SECONDS)
    cursor = await conn.execute(
        """UPDATE imports SET attempts = attempts + 1, modified_at = now()
           WHERE status = 'processing' AND modified_at < now() - %s AND attempts < %s
           RETURNING task_id""",
        (stale, common.MAX_ATTEMPTS),
    )
    for row in await cursor.fetchall():
        log.warning("Resubmitting %s", row["task_id"])
        submit(row["task_id"])

    cursor = await conn.execute(
        """UPDATE imports SET status = 'error', error_code = 'WORKER_LOST', modified_at = now(),
                              message = 'The import stopped unexpectedly. Please try again.'
           WHERE status = 'processing' AND modified_at < now() - %s
           RETURNING task_id""",
        (stale,),
    )
    for row in await cursor.fetchall():
        await notify(conn, row["task_id"])


async def recover_overdue(conn, storage) -> None:
    """Jobs still pending after their URL expired: a lost webhook, or an abandoned upload."""
    cursor = await conn.execute(
        "SELECT task_id FROM imports WHERE status = 'pending' AND expires_at < now() - %s",
        (timedelta(seconds=common.STALE_SECONDS),),  # grace for an upload that just landed
    )
    for row in await cursor.fetchall():
        task_id = row["task_id"]
        arrived = await asyncio.to_thread(file_exists, storage, task_id)
        status, code, message = (
            ("processing", "", "")
            if arrived
            else ("error", "UPLOAD_EXPIRED", "No file arrived before the upload link expired.")
        )
        claimed = await conn.execute(
            """UPDATE imports SET status = %s, folder = %s, error_code = %s, message = %s,
                                  modified_at = now()
               WHERE task_id = %s AND status = 'pending'""",
            (status, common.PERSISTENT_BUCKET, code, message, task_id),
        )
        if claimed.rowcount:
            await notify(conn, task_id)
            if arrived:
                submit(task_id)


def file_exists(storage, task_id: uuid.UUID) -> bool:
    try:
        storage.head_object(Bucket=common.PERSISTENT_BUCKET, Key=common.object_key(task_id))
        return True
    except ClientError:
        return False


async def sweep() -> None:
    storage = common.s3()
    while True:
        await asyncio.sleep(common.SWEEP_SECONDS)
        try:
            async with await connect() as conn:
                await recover_stale(conn)
                await recover_overdue(conn, storage)
                await conn.commit()
        except Exception:
            log.exception("Sweep failed")


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    global pool
    pool = new_pool()
    tasks = [asyncio.create_task(listen()), asyncio.create_task(sweep())]
    yield
    for task in tasks:
        task.cancel()
    pool.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="Async Import Pipeline", lifespan=lifespan)
signer = common.s3("AWS_PUBLIC_ENDPOINT")


class ImportRequest(BaseModel):
    filename: str | None = Field(default=None, max_length=255)


@app.post("/imports", status_code=201)
async def create_import(body: ImportRequest | None = None) -> dict:
    task_id = uuid.uuid4()
    expires_at = datetime.now(UTC) + timedelta(seconds=common.SIGNED_URL_TTL)
    async with await connect() as conn:
        await conn.execute(
            "INSERT INTO imports (task_id, filename, folder, expires_at) VALUES (%s, %s, %s, %s)",
            (task_id, body.filename if body else None, common.ENTRY_BUCKET, expires_at),
        )
    url = signer.generate_presigned_url(
        "put_object",
        Params={"Bucket": common.ENTRY_BUCKET, "Key": common.object_key(task_id)},
        ExpiresIn=common.SIGNED_URL_TTL,
    )
    return {"url": url, "task_id": str(task_id), "token": common.task_token(task_id)}


@app.get("/imports/{task_id}")
async def get_import(task_id: uuid.UUID, x_import_token: str = Header(default="")) -> dict:
    if not valid_token(task_id, x_import_token):
        raise HTTPException(404, "Import not found")
    job = await read_job(task_id)
    if job is None:
        raise HTTPException(404, "Import not found")
    return to_result(job)


@app.post("/webhook/import")
async def webhook(request: Request, x_signature: str = Header(default="")) -> dict:
    raw = await request.body()
    if not common.verify(raw, x_signature):
        raise HTTPException(401, "Invalid signature")

    body = json.loads(raw)
    task_id = common.task_id_from_key(body.get("filename", ""))
    if task_id is None:
        raise HTTPException(422, "Invalid filename")

    accepted = body.get("status") == "success"
    if accepted and not body.get("folder"):
        raise HTTPException(422, "Missing folder")

    async with await connect() as conn:
        # The status condition makes duplicates harmless, and it is atomic across replicas.
        result = await conn.execute(
            """UPDATE imports SET status = %s, folder = COALESCE(%s, folder), error_code = %s,
                                  message = %s, modified_at = now()
               WHERE task_id = %s AND status = 'pending'""",
            (
                "processing" if accepted else "error",
                body.get("folder"),
                body.get("error_code", ""),
                body.get("message", ""),
                task_id,
            ),
        )
        if not result.rowcount:
            return {"status": "ignored"}
        await notify(conn, task_id)

    if accepted:
        submit(task_id)
    return {"status": "accepted"}


def valid_token(task_id: uuid.UUID, token: object) -> bool:
    return isinstance(token, str) and common.verify(f"task:{task_id}".encode(), token)


@app.websocket("/ws")
async def updates(websocket: WebSocket) -> None:
    await websocket.accept()
    watching: set[uuid.UUID] = set()
    try:
        while True:
            message = await websocket.receive_json()
            try:
                task_id = uuid.UUID(str(message.get("task_id")))
            except ValueError:
                continue
            if message.get("action") != "subscribe" or not valid_token(
                task_id, message.get("token")
            ):
                continue
            # Register first, then read: a result that lands in between is sent, never missed.
            subscribers[task_id].add(websocket)
            watching.add(task_id)
            job = await read_job(task_id)
            if job is not None:
                await websocket.send_json(to_result(job))
    except (WebSocketDisconnect, json.JSONDecodeError, AttributeError):
        pass
    finally:
        for task_id in watching:
            subscribers.get(task_id, set()).discard(websocket)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "healthy"}


@app.get("/samples/{name}.pdf")
def sample(name: str) -> Response:
    lines = {"valid": sample_pdf.VALID, "invalid": sample_pdf.INVALID}.get(name)
    if lines is None:
        raise HTTPException(404, "Unknown sample")
    return Response(sample_pdf.build_pdf(lines), media_type="application/pdf")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")
