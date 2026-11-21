"""FastAPI application. Serves the JSON API under /api and the built frontend at /."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import session_scope
from .security import auth

log = logging.getLogger("agentoffice")

ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]", "testserver"}
PUBLIC_PATHS = {"/api/health", "/api/auth/session"}
CLIENT_HEADER = "x-agentoffice-client"


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .catalog import seed

    for d in (settings.data_dir, settings.uploads_dir, settings.exports_dir, settings.sandbox_dir):
        d.mkdir(parents=True, exist_ok=True)
    auth.api_token()  # create the per-install token on first start
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
        # Authentication: every API call needs the per-install token (cookie or bearer header).
        path = request.url.path
        if path.startswith("/api") and path not in PUBLIC_PATHS and request.method != "OPTIONS":
            if not auth.valid(auth.request_token(request.headers, request.cookies)):
                return JSONResponse({"detail": "Not authorized. Open AgentOffice with ./agentoffice open"},
                                    status_code=401)
        # CSRF protection: browsers cannot attach this custom header cross-origin without a
        # CORS preflight, which we only grant to the local dev server origin.
        if request.url.path.startswith("/api") and request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get(CLIENT_HEADER) != "1":
                return JSONResponse({"detail": "Missing X-AgentOffice-Client header"}, status_code=403)
        return await call_next(request)

    app.add_middleware(CORSMiddleware, allow_origins=[settings.dev_origin, "http://localhost:5173"],
                       allow_methods=["*"], allow_headers=["*"], allow_credentials=False)

    from .api import routes

    @app.get("/api/auth/session", include_in_schema=False)
    async def session(token: str = ""):
        """Exchange the launcher's sign-in link for an HttpOnly, SameSite=Strict cookie, then go
        to the app (fixed target, so this can't be used as an open redirect)."""
        if not auth.valid(token):
            return JSONResponse({"detail": "Invalid token. Run ./agentoffice open"}, status_code=401)
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(auth.COOKIE, token, httponly=True, samesite="strict", path="/", max_age=30 * 24 * 3600)
        resp.headers["Referrer-Policy"] = "no-referrer"
        return resp

    @app.get("/api/auth/check", include_in_schema=False)
    async def auth_check():
        return {"ok": True}

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
