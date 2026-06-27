import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from api.task_manage import get_task_manager
from core.document.artifact_generator import DocumentArtifactGenerator

logger = logging.getLogger(__name__)
router = APIRouter()

_TOOL_HANDLERS = {
    "doc-layout-recognition": DocumentArtifactGenerator.build_layout_json,
    "doc-content-extraction": DocumentArtifactGenerator.build_content_json,
    "doc-annotated-pdf": DocumentArtifactGenerator.build_annotated_file,
    "doc-detail-pdf": DocumentArtifactGenerator.build_detail_pdf,
}


@router.get("/tools/api/v1/{tool_id}/result/{task_id}")
async def result(tool_id: str, task_id: str):
    task = get_task_manager().get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}")

    handler = _TOOL_HANDLERS.get(tool_id)
    if handler is None:
        raise HTTPException(status_code=400, detail=f"tool_id not found: {tool_id}")

    try:
        data = handler(task.file_path)
    except Exception as exc:
        logger.exception("result build error for task_id=%s tool_id=%s", task_id, tool_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return JSONResponse({
        "code": 0,
        "message": "result success",
        "catch": False,
        "data": {"data": data},
    })

