"""Runs in a separate process. Builds its own clients because connections cannot be pickled."""

import logging
import uuid

import psycopg

from importer import common
from importer.parser import ImportRejected, parse_pdf

log = logging.getLogger("importer.worker")


def finish(conn, task_id, *, status, error_code="", message="", record_ids=()):
    conn.execute(
        """UPDATE imports SET status = %s, error_code = %s, message = %s, record_ids = %s,
                              modified_at = now()
           WHERE task_id = %s""",
        (status, error_code, message, list(record_ids), task_id),
    )
    conn.execute("SELECT pg_notify(%s, %s)", (common.NOTIFY_CHANNEL, str(task_id)))


def run(task_id: uuid.UUID) -> None:
    """Never raises: whatever happens, the job row ends in a final state."""
    with psycopg.connect(common.DATABASE_URL) as conn:
        try:
            _import(conn, task_id)
        except ImportRejected as exc:
            conn.rollback()
            finish(conn, task_id, status="error", error_code="INVALID_CONTENT", message=str(exc))
        except Exception:
            log.exception("Import %s failed", task_id)
            conn.rollback()
            finish(
                conn,
                task_id,
                status="error",
                error_code="IMPORT_FAILED",
                message="The file could not be processed.",
            )


def _import(conn, task_id: uuid.UUID) -> None:
    # The row lock makes a second run of the same job wait, then see it is already done.
    job = conn.execute(
        "SELECT status, folder FROM imports WHERE task_id = %s FOR UPDATE", (task_id,)
    ).fetchone()
    if job is None or job[0] != "processing":
        return

    body = common.s3().get_object(Bucket=job[1], Key=common.object_key(task_id))["Body"]
    records = parse_pdf(body.read())

    # Sorted so two imports that share SKUs lock rows in the same order and cannot deadlock.
    ids = [
        conn.execute(
            """INSERT INTO records (sku, name, price) VALUES (%s, %s, %s)
               ON CONFLICT (sku) DO UPDATE
               SET name = excluded.name, price = excluded.price, modified_at = now()
               RETURNING id""",
            (record.sku, record.name, record.price),
        ).fetchone()[0]
        for record in sorted(records, key=lambda r: r.sku)
    ]
    finish(conn, task_id, status="success", record_ids=ids)
