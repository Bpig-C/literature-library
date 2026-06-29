import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.post("/tools/api/v1/{tool_id}/run")
async def run(tool_id: str, request: Request):
    body = await request.body()
    try:
        body_data = json.loads(body)
    except Exception:
        body_data = body.decode(errors="replace") if body else None

    return JSONResponse({
        "code": 0,
        "message": "run success",
        "data": {
            "tool_id": tool_id,
            "task_id": None,
            "status": "running",
            "input": body_data,
            "accepts_arbitrary_tool_id": True,
        },
    })
