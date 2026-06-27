from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from api.services.artifact_service import (
    get_artifact_file,
    get_package_path,
    guess_content_type,
    list_artifacts,
)
from api.services.parse_service import parse_metadata, submit_file
from api.task_manage import get_task_manager
from core.document.artifact_generator import DocumentArtifactGenerator

router = APIRouter(prefix="/api/v1", tags=["Agent API"])

_RESULT_HANDLERS = {
    "content": DocumentArtifactGenerator.build_content_json,
    "layout": DocumentArtifactGenerator.build_layout_json,
    "detail": DocumentArtifactGenerator.build_detail_pdf,
    "annotated": DocumentArtifactGenerator.build_annotated_file,
}


def _get_task_or_404(task_id: str):
    task = get_task_manager().get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}")
    return task


def _task_payload(task):
    return {
        "task_id": task.task_id,
        "status": task.status,
        "filename": task.file_name,
        "time_create": task.time_create,
        "time_finish": task.time_finish,
        "error": task.error_message,
        "backend": task.backend,
        "parse_method": task.parse_method,
        "result_url": f"/api/v1/tasks/{task.task_id}/result",
        "artifacts_url": f"/api/v1/tasks/{task.task_id}/artifacts",
        "package_url": f"/api/v1/tasks/{task.task_id}/artifacts/package",
    }


@router.post("/parse")
async def parse(
    file: UploadFile = File(...),
    backend: str = Form(""),
    parse_method: str = Form(""),
    return_package: bool = Form(True),
    metadata: str = Form(None),
):
    result = submit_file(
        await file.read(),
        file.filename or "",
        backend=backend,
        parse_method=parse_method,
        metadata=parse_metadata(metadata),
    )

    return JSONResponse({
        "code": 0,
        "message": "submit success",
        "data": {
            "task_id": result.task_id,
            "filename": result.filename,
            "status": result.status,
            "status_url": f"/api/v1/tasks/{result.task_id}",
            "result_url": f"/api/v1/tasks/{result.task_id}/result",
            "artifacts_url": f"/api/v1/tasks/{result.task_id}/artifacts",
            "package_url": f"/api/v1/tasks/{result.task_id}/artifacts/package" if return_package else "",
        },
    })


@router.get("/tasks/{task_id}")
async def task_status(task_id: str):
    return JSONResponse({
        "code": 0,
        "message": "status success",
        "data": _task_payload(_get_task_or_404(task_id)),
    })


@router.get("/tasks/{task_id}/result")
async def task_result(task_id: str, type: str = Query("content")):
    task = _get_task_or_404(task_id)
    handler = _RESULT_HANDLERS.get(type)
    if handler is None:
        raise HTTPException(status_code=400, detail=f"unsupported result type: {type}")

    return JSONResponse({
        "code": 0,
        "message": "result success",
        "data": {
            "task_id": task.task_id,
            "type": type,
            "result": handler(task.file_path),
        },
    })


@router.get("/tasks/{task_id}/artifacts", tags=["Artifacts"])
async def task_artifacts(task_id: str):
    return JSONResponse({
        "code": 0,
        "message": "artifacts success",
        "data": list_artifacts(_get_task_or_404(task_id)),
    })


@router.get("/tasks/{task_id}/artifacts/file", tags=["Artifacts"])
async def task_artifact_file(task_id: str, path: str = Query(...)):
    file_path = get_artifact_file(_get_task_or_404(task_id), path)
    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type=guess_content_type(file_path),
    )


@router.get("/tasks/{task_id}/artifacts/package", tags=["Artifacts"])
async def task_artifact_package(task_id: str):
    task = _get_task_or_404(task_id)
    package_path = get_package_path(task)
    return FileResponse(
        path=str(package_path),
        filename=f"document-parser-{task_id}.zip",
        media_type="application/zip",
    )
