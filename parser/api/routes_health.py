from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health")
async def health():
    return JSONResponse({"code": 0, "message": "ok", "data": {"status": "healthy"}})
