"""Acceptance tests against the running stack. Start it with `make up`, run with `make e2e`."""

import asyncio
import json
import subprocess
import time
import uuid

import boto3
import httpx
import psycopg
import pytest
import websockets
from botocore.config import Config

from importer import common, sample_pdf

pytestmark = pytest.mark.e2e
API = "http://localhost:8100"
REPLICA_WS = "ws://localhost:8101/ws"
API_WS = "ws://localhost:8100/ws"
TIMEOUT = 30


def create() -> dict:
    response = httpx.post(f"{API}/imports", json={"filename": "it's a sheet.pdf"})
    assert response.status_code == 201
    return response.json()


def upload(job: dict, body: bytes) -> None:
    assert httpx.put(job["url"], content=body).status_code == 200


def status(job: dict) -> dict:
    response = httpx.get(
        f"{API}/imports/{job['task_id']}", headers={"X-Import-Token": job["token"]}
    )
    assert response.status_code == 200
    return response.json()


def wait_final(job: dict) -> dict:
    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        result = status(job)
        if result["status"] in ("success", "error"):
            return result
        time.sleep(0.2)
    raise AssertionError(f"Job did not finish: {status(job)}")


def unique_sheet() -> tuple[bytes, list[str]]:
    skus = [f"T-{uuid.uuid4().hex[:8]}" for _ in range(2)]
    lines = ["sku,name,price", *[f"{sku},Test item,10.00" for sku in skus]]
    return sample_pdf.build_pdf(lines), skus


def sql(query: str, *params):
    with psycopg.connect(common.DATABASE_URL, autocommit=True) as conn:
        cursor = conn.execute(query, params)
        return cursor.fetchall() if cursor.description else None


def post_webhook(payload: dict, signature: str | None = None) -> httpx.Response:
    body = json.dumps(payload).encode()
    return httpx.post(
        f"{API}/webhook/import",
        content=body,
        headers={"X-Signature": signature or common.sign(body)},
    )


def entry_keys() -> set[str]:
    listing = common.s3().list_objects_v2(Bucket=common.ENTRY_BUCKET)
    return {item["Key"] for item in listing.get("Contents", [])}


def test_valid_file_creates_records_and_moves_the_file():
    body, skus = unique_sheet()
    job = create()
    upload(job, body)
    result = wait_final(job)
    assert result["status"] == "success"
    assert len(result["record_ids"]) == 2
    assert result["filename"] == "it's a sheet.pdf"  # a quote is data, not SQL
    assert len(sql("SELECT 1 FROM records WHERE sku = ANY(%s)", skus)) == 2
    key = common.object_key(job["task_id"])
    assert key not in entry_keys()
    assert common.s3().head_object(Bucket=common.PERSISTENT_BUCKET, Key=key)


def test_executable_renamed_to_pdf_is_rejected_at_the_edge():
    job = create()
    upload(job, b"MZ\x90\x00 not a pdf")
    result = wait_final(job)
    assert result["error_code"] == "INVALID_FILE_TYPE"
    assert common.object_key(job["task_id"]) not in entry_keys()


def test_oversized_file_is_rejected_at_the_edge():
    job = create()
    upload(job, b"%PDF-" + b"0" * common.MAX_FILE_SIZE)
    result = wait_final(job)
    assert result["error_code"] == "FILE_TOO_LARGE"
    assert common.object_key(job["task_id"]) not in entry_keys()


def test_one_bad_row_writes_nothing():
    sku = f"T-{uuid.uuid4().hex[:8]}"
    job = create()
    upload(job, sample_pdf.build_pdf(["sku,name,price", f"{sku},Good,1.00", "BAD,Row,oops"]))
    result = wait_final(job)
    assert result["error_code"] == "INVALID_CONTENT"
    assert "Line 3" in result["message"]
    assert sql("SELECT 1 FROM records WHERE sku = %s", sku) == []


def test_duplicate_webhook_is_ignored():
    body, _ = unique_sheet()
    job = create()
    upload(job, body)
    first = wait_final(job)
    payload = {
        "status": "success",
        "filename": common.object_key(job["task_id"]),
        "folder": common.PERSISTENT_BUCKET,
    }
    assert post_webhook(payload).json() == {"status": "ignored"}
    assert wait_final(job)["record_ids"] == first["record_ids"]


def test_unsigned_webhook_is_refused():
    job = create()
    payload = {"status": "error", "filename": common.object_key(job["task_id"])}
    assert post_webhook(payload, signature="0" * 64).status_code == 401
    assert status(job)["status"] == "pending"


def test_status_needs_the_task_token():
    job = create()
    response = httpx.get(f"{API}/imports/{job['task_id']}", headers={"X-Import-Token": "wrong"})
    assert response.status_code == 404


async def next_final(socket) -> dict:
    while True:
        message = json.loads(await asyncio.wait_for(socket.recv(), TIMEOUT))
        if message["status"] in ("success", "error"):
            return message


def test_result_is_pushed_to_a_subscriber_on_another_replica():
    async def scenario():
        body, _ = unique_sheet()
        job = create()
        async with websockets.connect(REPLICA_WS) as socket:
            await socket.send(
                json.dumps(
                    {"action": "subscribe", "task_id": job["task_id"], "token": job["token"]}
                )
            )
            await asyncio.to_thread(upload, job, body)
            return await next_final(socket)

    assert asyncio.run(scenario())["status"] == "success"


def test_late_subscriber_gets_the_result_from_the_database():
    body, _ = unique_sheet()
    job = create()
    upload(job, body)
    wait_final(job)

    async def scenario():
        async with websockets.connect(API_WS) as socket:
            await socket.send(
                json.dumps(
                    {"action": "subscribe", "task_id": job["task_id"], "token": job["token"]}
                )
            )
            return await next_final(socket)

    assert asyncio.run(scenario())["status"] == "success"


def test_subscribe_with_a_bad_token_gets_nothing():
    job = create()

    async def scenario():
        async with websockets.connect(API_WS) as socket:
            await socket.send(
                json.dumps({"action": "subscribe", "task_id": job["task_id"], "token": "x"})
            )
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(socket.recv(), 1)

    asyncio.run(scenario())


def test_expired_signed_url_is_refused():
    client = boto3.client(
        "s3",
        endpoint_url="http://localhost:4577",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    url = client.generate_presigned_url(
        "put_object",
        Params={"Bucket": common.ENTRY_BUCKET, "Key": f"{uuid.uuid4()}.pdf"},
        ExpiresIn=1,
    )
    time.sleep(2)
    assert httpx.put(url, content=b"%PDF-").status_code == 403


def test_job_abandoned_by_a_dead_worker_is_resumed():
    body, _ = unique_sheet()
    job = create()
    key = common.object_key(job["task_id"])
    common.s3().put_object(Bucket=common.PERSISTENT_BUCKET, Key=key, Body=body)
    sql(
        """UPDATE imports SET status = 'processing', folder = %s,
                              modified_at = now() - interval '1 hour' WHERE task_id = %s""",
        common.PERSISTENT_BUCKET,
        job["task_id"],
    )
    assert wait_final(job)["status"] == "success"


def test_lost_webhook_is_recovered_from_storage():
    body, _ = unique_sheet()
    job = create()
    key = common.object_key(job["task_id"])
    common.s3().put_object(Bucket=common.PERSISTENT_BUCKET, Key=key, Body=body)
    sql(
        "UPDATE imports SET expires_at = now() - interval '1 minute' WHERE task_id = %s",
        job["task_id"],
    )
    assert wait_final(job)["status"] == "success"


def test_abandoned_upload_expires():
    job = create()
    sql(
        "UPDATE imports SET expires_at = now() - interval '1 minute' WHERE task_id = %s",
        job["task_id"],
    )
    assert wait_final(job)["error_code"] == "UPLOAD_EXPIRED"


KILL_WORKERS = """
import os, signal
for pid in filter(str.isdigit, os.listdir('/proc')):
    try:
        cmd = open(f'/proc/{pid}/cmdline').read()
    except OSError:
        continue
    if 'spawn_main' in cmd and int(pid) != os.getpid():
        os.kill(int(pid), signal.SIGKILL)
"""


def compose(*args: str) -> None:
    subprocess.run(["docker", "compose", *args], check=True, capture_output=True)


def test_imports_keep_working_after_a_worker_process_is_killed():
    compose("stop", "api-replica")  # alone, so no healthy replica can mask the failure
    try:
        body, _ = unique_sheet()
        job = create()
        upload(job, body)
        assert wait_final(job)["status"] == "success"  # the pool now has live workers

        compose("exec", "-T", "api", "python", "-c", KILL_WORKERS)

        body, _ = unique_sheet()
        job = create()
        upload(job, body)
        assert wait_final(job)["status"] == "success"
    finally:
        compose("up", "-d", "--wait", "api-replica")
