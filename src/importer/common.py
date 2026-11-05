"""Settings and small helpers shared by the API, the edge validator and the workers."""

import hashlib
import hmac
import os
import uuid

import boto3
from botocore.config import Config


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


DATABASE_URL = _env("DATABASE_URL", "postgresql://postgres:postgres@localhost:5544/imports")
SECRET = _env("IMPORT_SECRET").encode()  # no default: a known secret signs nothing
ENTRY_BUCKET = _env("ENTRY_BUCKET", "entry")
PERSISTENT_BUCKET = _env("PERSISTENT_BUCKET", "persistent")
API_WEBHOOK_URL = _env("API_WEBHOOK_URL", "http://localhost:8100/webhook/import")
MAX_FILE_SIZE = int(_env("MAX_FILE_SIZE", "5120000"))
SIGNED_URL_TTL = int(_env("SIGNED_URL_TTL", "900"))
WORKERS = int(_env("WORKERS", "4"))
SWEEP_SECONDS = float(_env("SWEEP_SECONDS", "30"))
STALE_SECONDS = int(_env("STALE_SECONDS", "120"))
MAX_ATTEMPTS = int(_env("MAX_ATTEMPTS", "3"))
EVENTS_QUEUE = _env("EVENTS_QUEUE", "upload-events")
NOTIFY_CHANNEL = "imports"


def aws(service: str, endpoint_var: str = "AWS_ENDPOINT"):
    return boto3.client(
        service,
        endpoint_url=_env(endpoint_var, "http://localhost:4577"),
        aws_access_key_id=_env("AWS_ACCESS_KEY_ID", "test"),
        aws_secret_access_key=_env("AWS_SECRET_ACCESS_KEY", "test"),
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def s3(endpoint_var: str = "AWS_ENDPOINT"):
    """Storage client. AWS_PUBLIC_ENDPOINT is the address the browser can reach."""
    return aws("s3", endpoint_var)


def object_key(task_id: uuid.UUID | str) -> str:
    return f"{task_id}.pdf"


def task_id_from_key(key: str) -> uuid.UUID | None:
    """The filename is the correlation ID. Anything else is not one of our uploads."""
    stem, _, ext = key.rpartition(".")
    try:
        return uuid.UUID(stem) if ext == "pdf" else None
    except ValueError:
        return None


def sign(payload: bytes) -> str:
    return hmac.new(SECRET, payload, hashlib.sha256).hexdigest()


def verify(payload: bytes, signature: str) -> bool:
    return hmac.compare_digest(sign(payload), signature)


def task_token(task_id: uuid.UUID | str) -> str:
    """Read capability for one job. Replace with a per-user check behind real auth."""
    return sign(f"task:{task_id}".encode())
