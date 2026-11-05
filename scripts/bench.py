"""Local benchmark: API cost per import, and API latency while imports run.

Run against the stack (`make up`), then `make bench`. Numbers are for this machine only.
"""

import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from importer import sample_pdf

API = "http://localhost:8100"
RUNS = 20


def percentile(values: list[float], share: float) -> float:
    return sorted(values)[min(len(values) - 1, int(len(values) * share))]


def sheet(size: int) -> bytes:
    # Real rows, padded with a PDF comment to reach the target size.
    pdf = sample_pdf.build_pdf(sample_pdf.VALID)
    return pdf + b"%" + b"0" * max(0, size - len(pdf) - 1)


def run_import(client: httpx.Client, body: bytes) -> tuple[float, float]:
    started = time.perf_counter()
    job = client.post(f"{API}/imports", json={}).json()
    api_ms = (time.perf_counter() - started) * 1000
    assert client.put(job["url"], content=body).status_code == 200
    while True:
        result = client.get(
            f"{API}/imports/{job['task_id']}", headers={"X-Import-Token": job["token"]}
        ).json()
        if result["status"] in ("success", "error"):
            assert result["status"] == "success", result
            return api_ms, time.perf_counter() - started
        time.sleep(0.02)


def main() -> None:
    print("| File size | API call p50 | End-to-end p50 | End-to-end p95 |")
    print("|---|---|---|---|")
    for label, size in (("2 KB", 2_000), ("1 MB", 1_000_000), ("5 MB", 5_000_000)):
        with httpx.Client(timeout=60) as client:
            body = sheet(size)
            runs = [run_import(client, body) for _ in range(RUNS)]
        api, total = [r[0] for r in runs], [r[1] for r in runs]
        print(
            f"| {label} | {statistics.median(api):.0f} ms | {statistics.median(total):.2f} s "
            f"| {percentile(total, 0.95):.2f} s |"
        )

    def probe(samples: list[float], stop: threading.Event) -> None:
        with httpx.Client() as client:
            while not stop.is_set():
                started = time.perf_counter()
                client.get(f"{API}/healthz")
                samples.append((time.perf_counter() - started) * 1000)
                time.sleep(0.01)

    idle: list[float] = []
    busy: list[float] = []
    stop = threading.Event()
    thread = threading.Thread(target=probe, args=(idle, stop))
    thread.start()
    time.sleep(3)
    stop.set()
    thread.join()

    stop = threading.Event()
    thread = threading.Thread(target=probe, args=(busy, stop))
    thread.start()
    body = sheet(5_000_000)

    def one(_: int) -> None:
        with httpx.Client(timeout=120) as client:
            run_import(client, body)

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(one, range(40)))
    stop.set()
    thread.join()
    print(f"\nAPI p95 idle: {percentile(idle, 0.95):.1f} ms")
    print(f"API p95 during 40 imports of 5 MB, 8 at a time: {percentile(busy, 0.95):.1f} ms")


if __name__ == "__main__":
    main()
