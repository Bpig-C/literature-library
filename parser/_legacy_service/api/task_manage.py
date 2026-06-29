"""
TaskManager — 任务记录管理器，持有 MinerU_OP 和 XML_OP 实例。
通过 FastAPI lifespan 初始化，避免模块导入时启动后台线程。
"""

import hashlib
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Optional

from config import config
from core.mineru.mineru_op import MinerU_OP
from core.xml.xml_op import XML_OP

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent


def get_share_dir() -> Path:
    share_dir = Path(config.share_dir)
    if not share_dir.is_absolute() and share_dir == Path("./Datas"):
        return BASE_DIR / "Datas"
    return share_dir


def get_uploads_dir() -> Path:
    return get_share_dir() / "uploads"


@dataclass
class Task:
    task_id: str
    original_file_path: str
    file_path: str
    dir: str
    file_name: str
    status: str
    time_create: str
    time_finish: str = ""
    doc_annotated_pdf_path: str = ""
    doc_layout_recognition_path: str = ""
    doc_detail_pdf_path: str = ""
    doc_content_extraction_path: str = ""
    error_message: str = ""
    backend: str = ""
    parse_method: str = ""
    artifact_dir: str = ""
    result_zip_path: str = ""
    metadata: dict = field(default_factory=dict)


class TaskManager:
    """全局任务管理器，由 server/app.py 在启动时创建。"""

    def __init__(self):
        self._lock = Lock()
        self._started = False
        self.mineru_op = MinerU_OP()
        self.xml_op = XML_OP()
        self.task_records: dict[str, Task] = {}
        self.load_task_cache()

    def start(self) -> None:
        if self._started:
            logger.info("TaskManager already started")
            return
        self.mineru_op.start(worker_count=config.mineru_worker_count)
        self._started = True
        logger.info("TaskManager started: %s", config.mineru_worker_count)

    def stop(self) -> None:
        if not self._started:
            return
        self.mineru_op.stop()
        self._started = False
        logger.info("TaskManager stopped")

    @staticmethod
    def make_task_id(file_bytes: bytes, filename: str) -> str:
        digest = hashlib.sha256(file_bytes + filename.encode()).hexdigest()
        return str(int(digest[:16], 16))

    def update_task_record(self, is_finish: bool, path: str, task_id: str, message: str = "") -> None:
        with self._lock:
            if task_id not in self.task_records:
                logger.warning("update_task_record: task_id=%s not found", task_id)
                return
            task = self.task_records[task_id]
            task.status = "succeeded" if is_finish else "failed"
            task.time_finish = str(int(time.time_ns()))
            task.error_message = "" if is_finish else message
            self.refresh_task_artifacts(task)
            logger.info("Task %s -> %s (%s)", task_id, task.status, path)

    def get_task(self, task_id: str) -> Optional[Task]:
        with self._lock:
            return self.task_records.get(task_id)

    def set_task(self, task_id: str, task: Task) -> None:
        with self._lock:
            self.task_records[task_id] = task

    @staticmethod
    def refresh_task_artifacts(task: Task) -> None:
        artifact_dir = Path(task.artifact_dir or task.dir or "").resolve()
        if not artifact_dir.exists():
            return

        def first_match(pattern: str) -> str:
            matches = sorted(artifact_dir.rglob(pattern))
            return str(matches[0].resolve()) if matches else ""

        task.artifact_dir = str(artifact_dir)
        task.result_zip_path = task.result_zip_path or first_match("*_result.zip")
        task.doc_annotated_pdf_path = task.doc_annotated_pdf_path or first_match("*_layout.pdf")
        task.doc_layout_recognition_path = task.doc_layout_recognition_path or first_match("*_doc_layout.json")
        task.doc_detail_pdf_path = task.doc_detail_pdf_path or first_match("*_doc_detail.json")
        task.doc_content_extraction_path = (
            task.doc_content_extraction_path
            or first_match("*_doc_content_extraction.json")
        )

    def load_task_cache(self) -> None:
        uploads_dir = get_uploads_dir()
        if not uploads_dir.exists():
            logger.info("load_task_cache: uploads dir not found: %s", uploads_dir)
            return

        def first_match(folder: Path, pattern: str) -> str:
            matches = sorted(folder.rglob(pattern))
            return str(matches[0].resolve()) if matches else ""

        loaded_tasks: dict[str, Task] = {}

        for task_dir in sorted(uploads_dir.iterdir()):
            if not task_dir.is_dir():
                continue

            task_id = task_dir.name
            content_list_files = sorted(task_dir.rglob("*_content_list.json"))
            root_files = sorted([path for path in task_dir.iterdir() if path.is_file()])
            pdf_files = [path for path in root_files if path.suffix.lower() == ".pdf"]
            non_pdf_files = [path for path in root_files if path.suffix.lower() != ".pdf"]

            if len(root_files) == 1 and len(pdf_files) == 1:
                original_file = pdf_files[0]
                file_path = pdf_files[0]
            elif non_pdf_files:
                original_file = non_pdf_files[0]
                file_path = pdf_files[0] if pdf_files else original_file
            elif pdf_files:
                original_file = pdf_files[0]
                file_path = pdf_files[0]
            else:
                logger.warning("load_task_cache: skip invalid task dir without source file: %s", task_dir)
                continue

            finish_time_ns = max(
                [path.stat().st_mtime_ns for path in content_list_files],
                default=task_dir.stat().st_mtime_ns,
            )
            create_time_ns = original_file.stat().st_mtime_ns if original_file.exists() else task_dir.stat().st_mtime_ns

            loaded_tasks[task_id] = Task(
                task_id=task_id,
                original_file_path=str(original_file.resolve()),
                file_path=str(file_path.resolve()),
                dir=str(task_dir.resolve()),
                file_name=original_file.name,
                status="succeeded" if content_list_files else "failed",
                time_create=str(create_time_ns),
                time_finish=str(finish_time_ns) if content_list_files else "",
                doc_annotated_pdf_path=first_match(task_dir, "*_layout.pdf"),
                doc_layout_recognition_path=first_match(task_dir, "*_doc_layout.json"),
                doc_detail_pdf_path=first_match(task_dir, "*_doc_detail.json"),
                doc_content_extraction_path=first_match(task_dir, "*_doc_content_extraction.json"),
                artifact_dir=str(task_dir.resolve()),
                result_zip_path=first_match(task_dir, "*_result.zip"),
            )

        with self._lock:
            self.task_records.update(loaded_tasks)

        logger.info("load_task_cache: loaded %d task(s)", len(loaded_tasks))


task_manager: TaskManager | None = None


def set_task_manager(manager: TaskManager | None) -> None:
    global task_manager
    task_manager = manager


def get_task_manager() -> TaskManager:
    if task_manager is None:
        raise RuntimeError("TaskManager is not initialized")
    return task_manager
