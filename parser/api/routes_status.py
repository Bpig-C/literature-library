from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from api.task_manage import get_task_manager

router = APIRouter(tags=["Legacy Tools"])


@router.get("/tools/api/v1/{tool_id}/status/{task_id}")
async def status(tool_id: str, task_id: str):
    task = get_task_manager().get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}")

    return JSONResponse({
        "code": 0,
        "message": "status success",
        "data": {
            "task_id": task.task_id,
            "status": task.status,
            "time_create": task.time_create,
            "time_finish": task.time_finish,
            "filename": task.file_name,
            "error": task.error_message,
        },
    })
