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
if DIST.exists():
    app.mount("/", StaticFiles(directory=str(DIST), html=True), name="static")
