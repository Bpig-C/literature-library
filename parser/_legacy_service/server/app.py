"""
FastAPI 应用组装：路由注册、CORS、认证中间件、lifespan。
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.openapi.utils import get_openapi
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

import api.task_manage as tm_module
from api import routes_agent, routes_health, routes_result, routes_run, routes_status, routes_submit
from api.task_manage import TaskManager
from config import config

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    manager = TaskManager()
    tm_module.set_task_manager(manager)
    manager.start()
    logger.info("Server started")
    try:
        yield
    finally:
        manager.stop()
        tm_module.set_task_manager(None)
        logger.info("Server stopped")


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Client-ID", "X-API-Key"],
    )

    app.mount("/html", StaticFiles(directory="./html", html=True), name="html")
    if config.expose_datas_static:
        config.share_dir.mkdir(parents=True, exist_ok=True)
        app.mount("/Datas", StaticFiles(directory=str(config.share_dir)), name="datas")

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        if (
            request.method == "OPTIONS"
            or request.url.path == "/health"
            or request.url.path.startswith("/html")
            or request.url.path in {"/docs", "/openapi.json", "/redoc"}
        ):
            return await call_next(request)

        client_id = request.headers.get("Client-ID", "")
        api_key = request.headers.get("X-API-Key", "")

        if not client_id or not api_key:
            return JSONResponse(
                status_code=401,
                content={"code": 401, "message": "Client-ID or X-API-Key is missing"},
            )

        expected = config.api_clients.get(client_id)
        if expected is None or expected != api_key:
            return JSONResponse(
                status_code=401,
                content={"code": 401, "message": "Unauthorized"},
            )

        return await call_next(request)

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"code": 500, "message": str(exc)},
        )

    app.include_router(routes_health.router)
    app.include_router(routes_agent.router)
    app.include_router(routes_submit.router)
    app.include_router(routes_status.router)
    app.include_router(routes_result.router)
    app.include_router(routes_run.router)

    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema

        schema = get_openapi(
            title="Document Parser API",
            version="0.1.0",
            description="Document parsing service with legacy tool endpoints and Agent API.",
            routes=app.routes,
        )
        components = schema.setdefault("components", {})
        security_schemes = components.setdefault("securitySchemes", {})
        security_schemes["ClientID"] = {
            "type": "apiKey",
            "in": "header",
            "name": "Client-ID",
        }
        security_schemes["APIKey"] = {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
        }

        for path, methods in schema.get("paths", {}).items():
            if path in {"/health"} or path.startswith("/html"):
                continue
            for operation in methods.values():
                if isinstance(operation, dict):
                    operation.setdefault("security", [{"ClientID": [], "APIKey": []}])

        app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = custom_openapi

    return app
