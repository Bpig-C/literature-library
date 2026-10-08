"""
MinerU 任务调度器。
使用优先级队列 + 后台工作线程，等价于 C++ MinerU_OP 类。
"""
import itertools
import logging
import queue
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from config import config
from .base_client import ParseRequest, PdfParseClient

logger = logging.getLogger(__name__)


@dataclass(order=True)
class _QueueItem:
    priority: int
    counter: int
    path: Path = field(compare=False)
    callback: Callable[..., None] = field(compare=False)
    backend: str = field(default="", compare=False)
    parse_method: str = field(default="", compare=False)


class MinerU_OP:

    def __init__(self):
        self._client: PdfParseClient = self._create_client()
        self._pq: queue.PriorityQueue[_QueueItem] = queue.PriorityQueue()
        self._counter = itertools.count()
        self._stop_event = threading.Event()
        self._workers: list[threading.Thread] = []
        self._lock = threading.Lock()
        self._queued_counters_by_path: dict[Path, set[int]] = defaultdict(set)
        self._cancelled_counters: set[int] = set()

    def _create_client(self) -> PdfParseClient:
        backend = (getattr(config, "mineru_backend", "cloud") or "cloud").lower()
        if backend == "cloud":
            from .cloud_client import CloudClient
            return CloudClient()
        if config.localcommand_mineru:
            from .local_client import LocalClient
            return LocalClient()
        else:
            from .web_client import WebClient
            return WebClient()

    def start(self, worker_count: int = 1) -> None:
        if worker_count < 1:
            raise ValueError("worker_count must be >= 1")

        with self._lock:
            alive_workers = [worker for worker in self._workers if worker.is_alive()]
            if alive_workers:
                logger.info(
                    "MinerU_OP workers already running, skip start (count=%d)",
                    len(alive_workers),
                )
                self._workers = alive_workers
                return

            self._stop_event.clear()
            self._workers = []
            for idx in range(worker_count):
                worker = threading.Thread(
                    target=self._execute_task,
                    name=f"MinerU-Worker-{idx + 1}",
                    daemon=True,
                )
                worker.start()
                self._workers.append(worker)

        logger.info("MinerU_OP worker threads started (count=%d)", worker_count)

    def stop(self) -> None:
        with self._lock:
            workers = [worker for worker in self._workers if worker.is_alive()]
            if not workers:
                self._workers = []
                logger.info("MinerU_OP worker threads already stopped")
                return

        self._stop_event.set()
        for idx in range(len(workers)):
            self._pq.put(
                _QueueItem(
                    priority=-999,
                    counter=-(idx + 1),
                    path=Path(),
                    callback=lambda *_: None,
                )
            )

        for worker in workers:
            worker.join()

        with self._lock:
            self._workers = []

        logger.info("MinerU_OP worker threads stopped")

    def push_task(
        self,
        priority: int,
        path: Path,
        callback: Callable[..., None],
        backend: str = "",
        parse_method: str = "",
    ) -> None:
        counter = next(self._counter)
        item = _QueueItem(
            priority=priority,
            counter=counter,
            path=path,
            callback=callback,
            backend=backend,
            parse_method=parse_method,
        )
        with self._lock:
            self._queued_counters_by_path[path].add(counter)
        self._pq.put(item)
        logger.info("Task queued (priority=%d): %s", priority, path)

    def remove_task(self, path: Path) -> None:
        """将指定路径的排队任务标记为取消，避免与多 worker 竞争队列。"""
        with self._lock:
            counters = self._queued_counters_by_path.pop(path, set())
            self._cancelled_counters.update(counters)

        if counters:
            logger.info("Cancelled %d queued task(s): %s", len(counters), path)

    def is_parsed(self, folder_path: Path) -> bool:
        return self._client.is_parsed(folder_path)

    def _execute_task(self) -> None:
        client = self._create_client()

        while True:
            try:
                item = self._pq.get(timeout=1.0)
            except queue.Empty:
                continue

            try:
                # 哨兵任务仅用于唤醒阻塞中的 worker。
                if not item.path.name:
                    if self._stop_event.is_set():
                        break
                    continue

                with self._lock:
                    counters = self._queued_counters_by_path.get(item.path)
                    if counters is not None:
                        counters.discard(item.counter)
                        if not counters:
                            self._queued_counters_by_path.pop(item.path, None)

                    if item.counter in self._cancelled_counters:
                        self._cancelled_counters.remove(item.counter)
                        logger.info("Skip cancelled task: %s", item.path)
                        continue

                logger.info("Processing task: %s", item.path)

                req = ParseRequest(
                    pdf_path=item.path,
                    output_dir=item.path.parent,
                    return_middle_json=config.parse_return_middle_json,
                    return_model_output=config.parse_return_model_output,
                    return_md=config.parse_return_md,
                    return_images=config.parse_return_images,
                    return_content_list=config.parse_return_content_list,
                    start_page_id=config.parse_start_page_id,
                    end_page_id=config.parse_end_page_id,
                    parse_method=item.parse_method or config.parse_method,
                    lang_list=config.parse_lang_list,
                    server_url=config.parse_server_url,
                    backend=item.backend or config.parse_backend,
                    table_enable=config.parse_table_enable,
                    formula_enable=config.parse_formula_enable,
                    response_format_zip=config.parse_response_format_zip,
                )

                try:
                    ok, msg = client.parse_pdf(req)
                except Exception as e:
                    ok, msg = False, f"Exception during parse: {e}"
                    logger.exception("Unexpected error parsing %s", item.path)

                try:
                    item.callback(ok, str(item.path), msg)
                except Exception:
                    logger.exception("Error in task callback for %s", item.path)
            finally:
                self._pq.task_done()
