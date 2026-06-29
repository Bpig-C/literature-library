import mimetypes
import shutil
from pathlib import Path

from fastapi import HTTPException

from api.task_manage import Task


def get_task_artifact_dir(task: Task) -> Path:
    base = Path(task.artifact_dir or task.dir)
    if not base.exists() or not base.is_dir():
        raise HTTPException(status_code=404, detail=f"artifact dir not found for task: {task.task_id}")
    return base.resolve()


def ensure_safe_relative_path(base_dir: Path, relative_path: str) -> Path:
    if not relative_path:
        raise HTTPException(status_code=400, detail="path is required")

    candidate = (base_dir / relative_path).resolve()
    if candidate != base_dir and base_dir not in candidate.parents:
        raise HTTPException(status_code=400, detail="path is outside task artifact directory")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"artifact file not found: {relative_path}")
    return candidate


def guess_content_type(path: Path) -> str:
    content_type, _ = mimetypes.guess_type(str(path))
    return content_type or "application/octet-stream"


def list_artifacts(task: Task) -> dict:
    base_dir = get_task_artifact_dir(task)
    files = []
    for path in sorted(base_dir.rglob("*")):
        if not path.is_file():
            continue
        relative_path = path.relative_to(base_dir).as_posix()
        files.append({
            "name": path.name,
            "relative_path": relative_path,
            "size": path.stat().st_size,
            "content_type": guess_content_type(path),
            "download_url": f"/api/v1/tasks/{task.task_id}/artifacts/file?path={relative_path}",
        })

    return {
        "task_id": task.task_id,
        "base_dir": str(base_dir),
        "files": files,
    }


def get_artifact_file(task: Task, relative_path: str) -> Path:
    return ensure_safe_relative_path(get_task_artifact_dir(task), relative_path)


def get_package_path(task: Task) -> Path:
    base_dir = get_task_artifact_dir(task)

    if task.result_zip_path:
        zip_path = Path(task.result_zip_path)
        if zip_path.exists() and zip_path.is_file():
            return zip_path.resolve()

    zip_files = sorted(base_dir.rglob("*_result.zip"))
    if zip_files:
        return zip_files[0].resolve()

    package_dir = base_dir.parent / "_packages"
    package_dir.mkdir(parents=True, exist_ok=True)
    package_base = package_dir / f"document-parser-{task.task_id}"
    zip_file = Path(shutil.make_archive(str(package_base), "zip", root_dir=base_dir))
    task.result_zip_path = str(zip_file.resolve())
    return zip_file.resolve()
