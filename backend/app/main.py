"""FastAPI application. Serves the JSON API under /api and the built frontend at /."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import session_scope

log = logging.getLogger("agentoffice")

ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]", "testserver"}
CLIENT_HEADER = "x-agentoffice-client"


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .catalog import seed

    for d in (settings.data_dir, settings.uploads_dir, settings.exports_dir, settings.sandbox_dir):
        d.mkdir(parents=True, exist_ok=True)
    with session_scope() as db:
        seed(db)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="AgentOffice", version="1.0.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        # DNS-rebinding protection: only accept loopback host names.
        raw_host = request.headers.get("host") or ""
        host = raw_host[: raw_host.find("]") + 1] if raw_host.startswith("[") else raw_host.split(":")[0]
        if host not in ALLOWED_HOSTS:
            return JSONResponse({"detail": "Host not allowed"}, status_code=403)
        # CSRF protection: browsers cannot attach this custom header cross-origin without a
        # CORS preflight, which we only grant to the local dev server origin.
        if request.url.path.startswith("/api") and request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get(CLIENT_HEADER) != "1":
                return JSONResponse({"detail": "Missing X-AgentOffice-Client header"}, status_code=403)
        return await call_next(request)

    app.add_middleware(CORSMiddleware, allow_origins=[settings.dev_origin, "http://localhost:5173"],
                       allow_methods=["*"], allow_headers=["*"], allow_credentials=False)

    from .api import routes

    app.include_router(routes.router, prefix="/api")

    dist = settings.frontend_dist
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            target = (dist / path).resolve()
            if path and target.is_file() and dist.resolve() in target.parents:
                return FileResponse(target)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
