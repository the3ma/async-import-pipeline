"""Edge validator: the local stand-in for a storage-triggered cloud function.

Rejects bad files by reading only the object's size and first bytes, then tells the API.
Storage events arrive on a queue, so they wait safely if this process is down.
"""

import json
import logging
import time
import urllib.parse
import urllib.request

from importer import common

log = logging.getLogger("importer.edge")

RETRIES = 3
RETRY_BASE_SECONDS = 1
SIGNATURE = b"%PDF-"


def validate(size: int, first_bytes: bytes, max_size: int) -> str | None:
    if size > max_size:
        return "FILE_TOO_LARGE"
    if not first_bytes.startswith(SIGNATURE):
        return "INVALID_FILE_TYPE"
    return None


def notify(payload: dict) -> bool:
    body = json.dumps(payload).encode()
    request = urllib.request.Request(  # noqa: S310 - fixed internal URL from configuration
        common.API_WEBHOOK_URL,
        data=body,
        headers={"Content-Type": "application/json", "X-Signature": common.sign(body)},
    )
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(request, timeout=30):  # noqa: S310
                return True
        except OSError as exc:
            log.warning("Webhook attempt %d failed: %s", attempt + 1, exc)
            if attempt < RETRIES - 1:
                time.sleep(RETRY_BASE_SECONDS * 2**attempt)
    # Not fatal: the API sweeper finds the moved file and resumes the job.
    log.error("All attempts to send result failed: %s", payload)
    return False


def handle(key: str, size: int) -> None:
    storage = common.s3()
    if common.task_id_from_key(key) is None:
        log.warning("Deleting unexpected object %s", key)
        storage.delete_object(Bucket=common.ENTRY_BUCKET, Key=key)
        return

    try:
        first_bytes = (
            storage.get_object(Bucket=common.ENTRY_BUCKET, Key=key, Range="bytes=0-4")[
                "Body"
            ].read()
            if size
            else b""
        )
    except storage.exceptions.NoSuchKey:
        return  # a redelivered event for a file that was already handled

    error_code = validate(size, first_bytes, common.MAX_FILE_SIZE)
    if error_code:
        storage.delete_object(Bucket=common.ENTRY_BUCKET, Key=key)
        limit_kb = common.MAX_FILE_SIZE // 1000
        messages = {
            "FILE_TOO_LARGE": f"The file is larger than the {limit_kb} KB limit.",
            "INVALID_FILE_TYPE": "The file is not a valid PDF.",
        }
        notify(
            {
                "status": "error",
                "filename": key,
                "error_code": error_code,
                "message": messages[error_code],
            }
        )
        return

    source = {"Bucket": common.ENTRY_BUCKET, "Key": key}
    storage.copy_object(Bucket=common.PERSISTENT_BUCKET, Key=key, CopySource=source)
    storage.delete_object(**source)
    notify({"status": "success", "filename": key, "folder": common.PERSISTENT_BUCKET})


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    queue = common.aws("sqs")
    url = queue.get_queue_url(QueueName=common.EVENTS_QUEUE)["QueueUrl"]
    while True:
        response = queue.receive_message(QueueUrl=url, WaitTimeSeconds=10, MaxNumberOfMessages=10)
        for message in response.get("Messages", []):
            try:
                for record in json.loads(message["Body"]).get("Records", []):
                    obj = record["s3"]["object"]
                    handle(urllib.parse.unquote_plus(obj["key"]), int(obj.get("size", 0)))
            except Exception:
                log.exception("Event failed, the queue will redeliver it")
                continue
            queue.delete_message(QueueUrl=url, ReceiptHandle=message["ReceiptHandle"])


if __name__ == "__main__":
    main()
