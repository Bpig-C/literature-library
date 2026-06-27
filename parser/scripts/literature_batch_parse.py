"""Batch parse migrated literature PDFs through the Agent API.

The runner is resumable. It keeps a JSON ledger under the literature library,
stores per-source outputs under works/{work_id}/parsed/mineru/{source_file_id},
and updates SQLite parse run records after each task.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.literature_inventory import DEFAULT_OUTPUT_ROOT

try:
    sys.stdout.reconfigure(errors="backslashreplace")
    sys.stderr.reconfigure(errors="backslashreplace")
except Exception:
    pass


DEFAULT_API_BASE = "http://127.0.0.1:18201"
DEFAULT_CLIENT_ID = "test_client"
DEFAULT_API_KEY = "test_key"
DEFAULT_BACKEND = "pipeline"
DEFAULT_PARSE_METHOD = "auto"
DEFAULT_MINERU_HEALTH_URL = "http://127.0.0.1:18200/health"

SMALL_LIMIT = 5 * 1024 * 1024
MEDIUM_LIMIT = 20 * 1024 * 1024
TRANSIENT_FAILURE_KINDS = {"transport", "timeout"}


@dataclass(frozen=True)
class ParseJob:
    work_id: str
    source_file_id: str
    original_name: str
    pdf_path: Path
    output_dir: Path
    size: int
    bucket: str
    content_sha256: str
    title: str


class Ledger:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": "literature_batch_parse_v1", "runs": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def get(self, run_key: str) -> dict[str, Any]:
        with self._lock:
            return dict(self.data.setdefault("runs", {}).get(run_key, {}))

    def update(self, run_key: str, **values: Any) -> dict[str, Any]:
        with self._lock:
            runs = self.data.setdefault("runs", {})
            current = dict(runs.get(run_key, {}))
            current.update(values)
            current["updated_at"] = utc_now()
            runs[run_key] = current
            self._save_locked()
            return current

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def bucket_for_size(size: int) -> str:
    if size < SMALL_LIMIT:
        return "small"
    if size < MEDIUM_LIMIT:
        return "medium"
    return "large"


def worker_count_for_bucket(bucket: str, override: int | None = None) -> int:
    if override is not None:
        return override
    return {"small": 2, "medium": 1, "large": 1}.get(bucket, 1)


def mineru_health_url_from_api_base(api_base: str) -> str:
    parsed = urllib.parse.urlparse(api_base)
    host = parsed.hostname or "127.0.0.1"
    scheme = parsed.scheme or "http"
    if host in {"localhost", "127.0.0.1"}:
        return DEFAULT_MINERU_HEALTH_URL
    return f"{scheme}://{host}:18200/health"


def classify_error(error: str) -> str:
    if "PDFium: Data format error" in error:
        return "invalid_pdf"
    if "WinError 206" in error or "文件名或扩展名太长" in error or "No such file or directory" in error:
        return "path_error"
    if "ConnectionResetError" in error or "RemoteDisconnected" in error or "Connection aborted" in error:
        return "transport"
    if "timeout" in error.lower():
        return "timeout"
    return "other"


def should_stop_for_transient_storm(results: list[dict[str, Any]], threshold: int) -> bool:
    if threshold <= 0 or len(results) < threshold:
        return False
    window = results[-threshold:]
    return all(item.get("failure_kind") in TRANSIENT_FAILURE_KINDS for item in window)


def upload_filename_for_attempt(job: ParseJob, attempt: int) -> str:
    suffix = f"-r{attempt}" if attempt > 1 else ""
    return f"{job.source_file_id}{suffix}.pdf"


def previous_failure_count(entry: dict[str, Any]) -> int:
    if entry.get("status") != "failed":
        return 0
    try:
        count = int(entry.get("failure_count") or 0)
    except (TypeError, ValueError):
        count = 0
    return max(count, 1)


def load_jobs(library_root: Path) -> list[ParseJob]:
    index_path = library_root / "index.json"
    if not index_path.exists():
        raise FileNotFoundError(f"library index not found: {index_path}")

    index = json.loads(index_path.read_text(encoding="utf-8"))
    jobs: list[ParseJob] = []
    for work in index.get("works", []):
        work_id = work["work_id"]
        title = work.get("title", "")
        for source in work.get("source_files", []):
            relative = source["library_relative_path"]
            pdf_path = library_root / relative
            size = pdf_path.stat().st_size if pdf_path.exists() else 0
            source_file_id = source["source_file_id"]
            jobs.append(
                ParseJob(
                    work_id=work_id,
                    source_file_id=source_file_id,
                    original_name=source.get("original_name", pdf_path.name),
                    pdf_path=pdf_path,
                    output_dir=library_root / "works" / work_id / "parsed" / "mineru" / source_file_id,
                    size=size,
                    bucket=bucket_for_size(size),
                    content_sha256=source.get("content_sha256", ""),
                    title=title,
                )
            )
    return sorted(jobs, key=lambda job: ({"small": 0, "medium": 1, "large": 2}[job.bucket], job.size, job.work_id))


def output_complete(job: ParseJob) -> bool:
    return (
        (job.output_dir / "task.json").exists()
        and (job.output_dir / "content.json").exists()
        and (job.output_dir / "content.md").exists()
        and (job.output_dir / "package.zip").exists()
    )


def recover_completed_outputs(jobs: list[ParseJob], ledger: Ledger, db_path: Path) -> int:
    recovered = 0
    for job in jobs:
        entry = ledger.get(job.source_file_id)
        if entry.get("status") == "succeeded" or not output_complete(job):
            continue

        task = json.loads((job.output_dir / "task.json").read_text(encoding="utf-8"))
        finished_at = entry.get("finished_at") or utc_now()
        run = {
            "work_id": job.work_id,
            "source_file_id": job.source_file_id,
            "task_id": task.get("task_id", entry.get("task_id", "")),
            "status": "succeeded",
            "backend": task.get("backend", entry.get("backend", DEFAULT_BACKEND)),
            "parse_method": task.get("parse_method", entry.get("parse_method", DEFAULT_PARSE_METHOD)),
            "started_at": entry.get("started_at", ""),
            "finished_at": finished_at,
            "output_dir": str(job.output_dir),
            "content_json_path": str(job.output_dir / "content.json"),
            "content_md_path": str(job.output_dir / "content.md"),
            "artifacts_path": str(job.output_dir / "artifacts.json"),
            "package_path": str(job.output_dir / "package.zip"),
            "error": "",
        }
        ledger.update(job.source_file_id, **run)
        update_work_metadata(job, run)
        update_database(db_path, job, run)
        recovered += 1
    return recovered


def classify_existing_failures(ledger: Ledger) -> int:
    updated = 0
    for source_file_id, entry in list(ledger.data.get("runs", {}).items()):
        if entry.get("status") != "failed" or entry.get("failure_kind"):
            continue
        ledger.update(source_file_id, failure_kind=classify_error(entry.get("error", "")))
        updated += 1
    return updated


def filter_jobs(
    jobs: list[ParseJob],
    ledger: Ledger,
    *,
    bucket: str,
    limit: int | None,
    retry_failed: bool,
    retry_transient: bool,
    include_completed: bool,
) -> list[ParseJob]:
    selected = []
    for job in jobs:
        if bucket != "all" and job.bucket != bucket:
            continue
        entry = ledger.get(job.source_file_id)
        status = entry.get("status")
        if not include_completed and (status == "succeeded" or output_complete(job)):
            continue
        if status == "failed":
            failure_kind = entry.get("failure_kind") or classify_error(entry.get("error", ""))
            if not retry_failed and not (retry_transient and failure_kind in {"transport", "path_error", "timeout"}):
                continue
        if status in {"submitted", "pending", "running"}:
            selected.append(job)
            if limit is not None and len(selected) >= limit:
                break
            continue
        selected.append(job)
        if limit is not None and len(selected) >= limit:
            break
    return selected


def request_json(url: str, *, headers: dict[str, str] | None = None, timeout: int = 30) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"HTTP {exc.code} for {url}: {body}") from exc


def health_check(label: str, url: str, *, headers: dict[str, str] | None = None, timeout: int = 10) -> None:
    try:
        payload = request_json(url, headers=headers, timeout=timeout)
    except Exception as exc:
        raise RuntimeError(f"{label} health check failed for {url}: {exc}") from exc
    data = payload.get("data", {})
    status = data.get("status") or payload.get("status")
    if status and str(status).lower() not in {"healthy", "ok"}:
        raise RuntimeError(f"{label} health check returned status={status!r} for {url}")


def post_multipart(
    url: str,
    fields: dict[str, str],
    file_path: Path,
    *,
    headers: dict[str, str],
    upload_filename: str | None = None,
    timeout: int,
) -> dict[str, Any]:
    boundary = f"----LiteratureBatchParse{int(time.time() * 1000)}"
    body = bytearray()
    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    body.extend(f"--{boundary}\r\n".encode())
    filename = upload_filename or file_path.name
    body.extend(f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode())
    body.extend(b"Content-Type: application/pdf\r\n\r\n")
    body.extend(file_path.read_bytes())
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())

    req = urllib.request.Request(
        url,
        data=bytes(body),
        headers={**headers, "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"HTTP {exc.code} for {url}: {body_text}") from exc


def download_binary(url: str, destination: Path, *, headers: dict[str, str], timeout: int) -> None:
    req = urllib.request.Request(url, headers=headers)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            with destination.open("wb") as handle:
                shutil.copyfileobj(response, handle)
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"HTTP {exc.code} for {url}: {body_text}") from exc


def content_to_markdown(payload: dict[str, Any]) -> str:
    items = payload.get("data", {}).get("result", [])
    lines = []
    for item in items:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if content is None:
            content = item.get("text", "")
        text = str(content).strip()
        if not text:
            continue
        content_type = str(item.get("content_type", "")).lower()
        if "title" in content_type or content_type in {"heading", "header"}:
            lines.append(f"## {text}")
        else:
            lines.append(text)
    return "\n\n".join(lines).strip() + "\n"


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def update_work_metadata(job: ParseJob, run: dict[str, Any]) -> None:
    metadata_path = job.output_dir.parents[2] / "metadata.json"
    if not metadata_path.exists():
        return
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    runs = [item for item in metadata.get("parse_runs", []) if item.get("source_file_id") != job.source_file_id]
    runs.append(run)
    metadata["parse_runs"] = runs
    metadata["parse_status"] = "succeeded" if all(item.get("status") == "succeeded" for item in runs) else "partial"
    save_json(metadata_path, metadata)


def ensure_parse_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS literature_parse_runs (
            id TEXT PRIMARY KEY,
            work_id TEXT NOT NULL,
            source_file_id TEXT NOT NULL,
            source_path TEXT NOT NULL,
            task_id TEXT,
            status TEXT NOT NULL,
            backend TEXT,
            parse_method TEXT,
            file_size INTEGER,
            started_at TEXT,
            finished_at TEXT,
            output_dir TEXT,
            error TEXT,
            content_json_path TEXT,
            content_md_path TEXT,
            package_path TEXT
        );
        """
    )


def update_database(db_path: Path, job: ParseJob, run: dict[str, Any]) -> None:
    conn = sqlite3.connect(db_path)
    try:
        ensure_parse_schema(conn)
        conn.execute(
            """
            INSERT OR REPLACE INTO literature_parse_runs(
                id, work_id, source_file_id, source_path, task_id, status, backend,
                parse_method, file_size, started_at, finished_at, output_dir, error,
                content_json_path, content_md_path, package_path
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"LPR-{job.source_file_id}",
                job.work_id,
                job.source_file_id,
                str(job.pdf_path),
                run.get("task_id", ""),
                run.get("status", ""),
                run.get("backend", ""),
                run.get("parse_method", ""),
                job.size,
                run.get("started_at", ""),
                run.get("finished_at", ""),
                run.get("output_dir", ""),
                run.get("error", ""),
                run.get("content_json_path", ""),
                run.get("content_md_path", ""),
                run.get("package_path", ""),
            ),
        )

        now = run.get("finished_at", utc_now())
        artifact_rows = [
            (
                f"PA-MINERU-{job.source_file_id}-content-json",
                job.work_id,
                job.source_file_id,
                "content_json",
                run.get("content_json_path", ""),
                "mineru",
                now,
                run.get("task_id", ""),
            ),
            (
                f"PA-MINERU-{job.source_file_id}-content-md",
                job.work_id,
                job.source_file_id,
                "content_markdown",
                run.get("content_md_path", ""),
                "mineru",
                now,
                run.get("task_id", ""),
            ),
            (
                f"PA-MINERU-{job.source_file_id}-package",
                job.work_id,
                job.source_file_id,
                "package_zip",
                run.get("package_path", ""),
                "mineru",
                now,
                run.get("task_id", ""),
            ),
        ]
        conn.executemany(
            """
            INSERT OR REPLACE INTO parse_artifacts(
                id, work_id, source_file_id, type, file_path, parser, parse_time, task_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            artifact_rows,
        )

        source_total = conn.execute(
            """
            SELECT COUNT(*) FROM library_migration_files
            WHERE work_id = ? AND role = 'canonical_source'
            """,
            (job.work_id,),
        ).fetchone()[0]
        if not source_total:
            source_total = conn.execute(
                "SELECT COUNT(*) FROM source_files WHERE work_id = ?",
                (job.work_id,),
            ).fetchone()[0]
        succeeded = conn.execute(
            """
            SELECT COUNT(*) FROM literature_parse_runs
            WHERE work_id = ? AND status = 'succeeded'
            """,
            (job.work_id,),
        ).fetchone()[0]
        failed = conn.execute(
            """
            SELECT COUNT(*) FROM literature_parse_runs
            WHERE work_id = ? AND status = 'failed'
            """,
            (job.work_id,),
        ).fetchone()[0]
        if succeeded >= source_total:
            work_status = "succeeded"
        elif succeeded > 0:
            work_status = "partial"
        elif failed > 0:
            work_status = "failed"
        else:
            work_status = "parsing"
        conn.execute(
            "UPDATE works SET parse_status = ?, updated_at = ? WHERE id = ?",
            (work_status, now, job.work_id),
        )
        conn.commit()
    finally:
        conn.close()


def poll_task(
    api_base: str,
    task_id: str,
    *,
    headers: dict[str, str],
    poll_interval: float,
    task_timeout: int,
) -> dict[str, Any]:
    deadline = time.time() + task_timeout
    status_url = f"{api_base}/api/v1/tasks/{task_id}"
    last_status = None
    while time.time() < deadline:
        payload = request_json(status_url, headers=headers, timeout=30)
        data = payload.get("data", {})
        current = data.get("status")
        if current != last_status:
            print(f"[poll] {task_id} -> {current}", flush=True)
            last_status = current
        if current in {"succeeded", "failed", "error"}:
            return data
        time.sleep(poll_interval)
    raise TimeoutError(f"task timeout: {task_id}")


def run_job(
    job: ParseJob,
    *,
    api_base: str,
    headers: dict[str, str],
    backend: str,
    parse_method: str,
    ledger: Ledger,
    db_path: Path,
    poll_interval: float,
    task_timeout: int,
    request_timeout: int,
    no_package: bool,
) -> dict[str, Any]:
    started_at = utc_now()
    entry = ledger.get(job.source_file_id)
    task_id = entry.get("task_id") if entry.get("status") in {"submitted", "pending", "running"} else ""

    try:
        previous_failures = previous_failure_count(entry)
        attempt = previous_failures + 1
        if not task_id:
            if not job.pdf_path.exists():
                raise FileNotFoundError(job.pdf_path)
            metadata = {
                "work_id": job.work_id,
                "source_file_id": job.source_file_id,
                "title": job.title,
                "original_name": job.original_name,
                "content_sha256": job.content_sha256,
            }
            submit = post_multipart(
                f"{api_base}/api/v1/parse",
                {
                    "backend": backend,
                    "parse_method": parse_method,
                    "return_package": "true",
                    "metadata": json.dumps(metadata, ensure_ascii=False),
                },
                job.pdf_path,
                headers=headers,
                upload_filename=upload_filename_for_attempt(job, attempt),
                timeout=request_timeout,
            )
            task_id = submit["data"]["task_id"]
            ledger.update(
                job.source_file_id,
                work_id=job.work_id,
                task_id=task_id,
                status="submitted",
                source_path=str(job.pdf_path),
                started_at=started_at,
                backend=backend,
                parse_method=parse_method,
                size=job.size,
                bucket=job.bucket,
            )

        status = poll_task(
            api_base,
            task_id,
            headers=headers,
            poll_interval=poll_interval,
            task_timeout=task_timeout,
        )
        if status.get("status") != "succeeded":
            raise RuntimeError(status.get("error") or f"task status={status.get('status')}")

        job.output_dir.mkdir(parents=True, exist_ok=True)
        content_payload = request_json(
            f"{api_base}/api/v1/tasks/{task_id}/result?type=content",
            headers=headers,
            timeout=request_timeout,
        )
        artifacts_payload = request_json(
            f"{api_base}/api/v1/tasks/{task_id}/artifacts",
            headers=headers,
            timeout=request_timeout,
        )
        content_json_path = job.output_dir / "content.json"
        content_md_path = job.output_dir / "content.md"
        artifacts_path = job.output_dir / "artifacts.json"
        task_path = job.output_dir / "task.json"
        package_path = job.output_dir / "package.zip"
        save_json(content_json_path, content_payload)
        content_md_path.write_text(content_to_markdown(content_payload), encoding="utf-8")
        save_json(artifacts_path, artifacts_payload)
        save_json(task_path, status)
        if not no_package:
            download_binary(
                f"{api_base}/api/v1/tasks/{task_id}/artifacts/package",
                package_path,
                headers=headers,
                timeout=max(request_timeout, 120),
            )

        finished_at = utc_now()
        run = {
            "work_id": job.work_id,
            "source_file_id": job.source_file_id,
            "task_id": task_id,
            "status": "succeeded",
            "backend": backend,
            "parse_method": parse_method,
            "started_at": entry.get("started_at") or started_at,
            "finished_at": finished_at,
            "output_dir": str(job.output_dir),
            "content_json_path": str(content_json_path),
            "content_md_path": str(content_md_path),
            "artifacts_path": str(artifacts_path),
            "package_path": str(package_path) if not no_package else "",
            "error": "",
        }
        ledger.update(job.source_file_id, **run)
        update_work_metadata(job, run)
        update_database(db_path, job, run)
        print(f"[ok] {job.source_file_id} {job.original_name}", flush=True)
        return run
    except Exception as exc:
        finished_at = utc_now()
        run = {
            "work_id": job.work_id,
            "source_file_id": job.source_file_id,
            "task_id": task_id,
            "status": "failed",
            "backend": backend,
            "parse_method": parse_method,
            "started_at": entry.get("started_at") or started_at,
            "finished_at": finished_at,
            "output_dir": str(job.output_dir),
            "error": str(exc),
            "failure_kind": classify_error(str(exc)),
            "failure_count": previous_failures + 1,
        }
        ledger.update(job.source_file_id, **run)
        update_database(db_path, job, run)
        print(f"[fail] {job.source_file_id} {job.original_name}: {exc}", flush=True)
        return run


def summarize_jobs(jobs: list[ParseJob]) -> dict[str, Any]:
    buckets: dict[str, dict[str, Any]] = {}
    for job in jobs:
        item = buckets.setdefault(job.bucket, {"count": 0, "size": 0})
        item["count"] += 1
        item["size"] += job.size
    return {
        bucket: {"count": value["count"], "size_mb": round(value["size"] / 1024 / 1024, 2)}
        for bucket, value in sorted(buckets.items())
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch parse migrated literature PDFs via document-parser Agent API.")
    parser.add_argument("--library-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--db", type=Path, default=None, help="SQLite path. Defaults to library-root/literature.sqlite.")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--client-id", default=DEFAULT_CLIENT_ID)
    parser.add_argument("--api-key", default=DEFAULT_API_KEY)
    parser.add_argument("--backend", default=DEFAULT_BACKEND)
    parser.add_argument("--parse-method", default=DEFAULT_PARSE_METHOD)
    parser.add_argument("--bucket", choices=["all", "small", "medium", "large"], default="all")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-workers", type=int, default=None)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument(
        "--retry-transient",
        action="store_true",
        help="Retry failures classified as transport/path/timeout while leaving invalid PDFs skipped.",
    )
    parser.add_argument("--include-completed", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-package", action="store_true")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--task-timeout", type=int, default=1800)
    parser.add_argument("--request-timeout", type=int, default=60)
    parser.add_argument("--ledger-name", default="parse_ledger.json")
    parser.add_argument(
        "--mineru-health-url",
        default=None,
        help="MinerU health endpoint checked before submitting jobs. Defaults to 127.0.0.1:18200 for local API.",
    )
    parser.add_argument("--skip-mineru-health", action="store_true")
    parser.add_argument(
        "--transient-stop-after",
        type=int,
        default=3,
        help="Stop the current bucket after this many consecutive transport/timeout failures. 0 disables.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    library_root = args.library_root.resolve()
    db_path = (args.db or library_root / "literature.sqlite").resolve()
    ledger = Ledger(library_root / args.ledger_name)
    headers = {"Client-ID": args.client_id, "X-API-Key": args.api_key}

    mineru_health_url = args.mineru_health_url or mineru_health_url_from_api_base(args.api_base)
    try:
        health_check("document-parser", f"{args.api_base}/health", timeout=10)
        if not args.skip_mineru_health:
            health_check("MinerU", mineru_health_url, timeout=10)
    except RuntimeError as exc:
        print(f"[preflight-fail] {exc}", file=sys.stderr, flush=True)
        raise SystemExit(2) from exc

    jobs = load_jobs(library_root)
    classified = classify_existing_failures(ledger)
    if classified:
        print(f"Classified existing failures: {classified}")
    recovered = recover_completed_outputs(jobs, ledger, db_path)
    if recovered:
        print(f"Recovered completed outputs: {recovered}")
    selected = filter_jobs(
        jobs,
        ledger,
        bucket=args.bucket,
        limit=args.limit,
        retry_failed=args.retry_failed,
        retry_transient=args.retry_transient,
        include_completed=args.include_completed,
    )
    print(f"Discovered jobs: {len(jobs)}")
    print(f"Selected jobs: {len(selected)}")
    print(f"Selected buckets: {json.dumps(summarize_jobs(selected), ensure_ascii=False)}")
    if not selected:
        return
    if args.dry_run:
        for job in selected[:50]:
            print(f"[dry-run] {job.bucket} {job.size / 1024 / 1024:.2f}MB {job.source_file_id} {job.pdf_path}")
        if len(selected) > 50:
            print(f"[dry-run] ... {len(selected) - 50} more")
        return

    buckets = ["small", "medium", "large"] if args.bucket == "all" else [args.bucket]
    all_results: list[dict[str, Any]] = []
    for bucket in buckets:
        bucket_jobs = [job for job in selected if job.bucket == bucket]
        if not bucket_jobs:
            continue
        workers = worker_count_for_bucket(bucket, args.max_workers)
        print(f"Starting bucket={bucket}, jobs={len(bucket_jobs)}, workers={workers}", flush=True)
        bucket_results: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            next_job_index = 0
            futures = set()

            def submit_next_job() -> None:
                nonlocal next_job_index
                if next_job_index >= len(bucket_jobs):
                    return
                job = bucket_jobs[next_job_index]
                next_job_index += 1
                futures.add(
                    executor.submit(
                        run_job,
                        job,
                        api_base=args.api_base,
                        headers=headers,
                        backend=args.backend,
                        parse_method=args.parse_method,
                        ledger=ledger,
                        db_path=db_path,
                        poll_interval=args.poll_interval,
                        task_timeout=args.task_timeout,
                        request_timeout=args.request_timeout,
                        no_package=args.no_package,
                    )
                )

            for _ in range(min(workers, len(bucket_jobs))):
                submit_next_job()

            while futures:
                done, futures = wait(futures, return_when=FIRST_COMPLETED)
                should_stop = False
                for future in done:
                    result = future.result()
                    all_results.append(result)
                    bucket_results.append(result)
                    succeeded = sum(1 for item in all_results if item.get("status") == "succeeded")
                    failed = sum(1 for item in all_results if item.get("status") == "failed")
                    print(
                        f"[progress] done={len(all_results)}/{len(selected)} succeeded={succeeded} failed={failed}",
                        flush=True,
                    )
                    if should_stop_for_transient_storm(bucket_results, args.transient_stop_after):
                        should_stop = True
                        break

                if should_stop:
                    print(
                        f"[stop] {args.transient_stop_after} consecutive transient failures; "
                        f"stop bucket={bucket} to protect the remaining ledger.",
                        flush=True,
                    )
                    for future in futures:
                        future.cancel()
                    executor.shutdown(wait=False, cancel_futures=True)
                    break

                while len(futures) < workers and next_job_index < len(bucket_jobs):
                    submit_next_job()

    succeeded = sum(1 for item in all_results if item.get("status") == "succeeded")
    failed = sum(1 for item in all_results if item.get("status") == "failed")
    print(f"Batch complete: succeeded={succeeded}, failed={failed}, total={len(all_results)}")


if __name__ == "__main__":
    main()
