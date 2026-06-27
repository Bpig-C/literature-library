from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse

from api.services.parse_service import submit_file

router = APIRouter(tags=["Legacy Tools"])


@router.post("/tools/api/v1/{tool_id}/submit")
async def submit(
    tool_id: str,
    files: UploadFile = File(...),
    extra_data: str = Form(None),
):
    result = submit_file(
        await files.read(),
        files.filename or "",
        extra_data=extra_data,
    )

    return JSONResponse({
        "code": 0,
        "message": "submit success",
        "data": {
            "task_id": result.task_id,
            "filename": result.filename,
            "file_path": result.file_path,
            "task_ids": [result.task_id],
        },
    })
