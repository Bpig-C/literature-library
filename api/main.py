"""FastAPI application for the literature library."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routes import duplicates, export, files, ingest, intake, metadata, parse, relations, works, classification, discovery, templates

app = FastAPI(title="Literature Library API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:19528"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(works.router, prefix="/api")
app.include_router(relations.router, prefix="/api")
app.include_router(duplicates.router, prefix="/api")
app.include_router(files.router, prefix="/api")
app.include_router(metadata.router, prefix="/api")
app.include_router(classification.router, prefix="/api")
app.include_router(intake.router, prefix="/api")
app.include_router(parse.router, prefix="/api")
app.include_router(ingest.router, prefix="/api")
app.include_router(discovery.router, prefix="/api")
app.include_router(templates.router, prefix="/api")
app.include_router(export.router, prefix="/api")

# Serve Vue build in production
DIST = Path(__file__).resolve().parents[1] / "web" / "dist"


@app.exception_handler(404)
async def spa_fallback(request, exc):
    """SPA fallback：前端路由（如 /inbox、/metadata）刷新/深链时回退到 index.html。

    API 路径保持 JSON 404；仅当 dist 存在时启用（开发模式走 vite）。
    """
    from fastapi.responses import FileResponse, JSONResponse

    if request.url.path.startswith("/api"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    index = DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse({"detail": "Not Found"}, status_code=404)


if DIST.exists():
    app.mount("/", StaticFiles(directory=str(DIST), html=True), name="static")
