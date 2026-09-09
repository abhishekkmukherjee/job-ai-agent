"""FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.router import api_router
from .config import FAKE_JOB_SITE_DIR, FRONTEND_DIST_DIR, get_settings
from .container import build_components, shutdown_components
from .database import init_db, session_scope
from .logging_config import configure_logging, get_logger
from .seed import seed_all

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    init_db()
    if settings.seed_on_startup:
        with session_scope() as db:
            seed_all(db, with_sample_jobs=settings.app_env != "production")
    await build_components(app)
    logger.info("%s started (env=%s)", settings.app_name, settings.app_env)
    try:
        yield
    finally:
        await shutdown_components(app)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Personal AI job-search and application assistant.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:  # pragma: no cover
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": f"Internal error: {type(exc).__name__}: {exc}"})

    @app.get("/api/health", tags=["system"])
    def health() -> dict:
        return {"status": "ok", "app": settings.app_name, "env": settings.app_env}

    app.include_router(api_router)

    # Local fake application site used to test browser automation safely.
    if settings.serve_fake_job_site and FAKE_JOB_SITE_DIR.exists():
        app.mount("/fake-job-site", StaticFiles(directory=str(FAKE_JOB_SITE_DIR), html=True), name="fake-job-site")

    # Built frontend (frontend/dist).  Any unknown non-API path falls back to index.html (SPA routing).
    if FRONTEND_DIST_DIR.exists() and (FRONTEND_DIST_DIR / "index.html").exists():
        assets_dir = FRONTEND_DIST_DIR / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str):
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not found")
            candidate = (FRONTEND_DIST_DIR / full_path).resolve()
            if full_path and candidate.is_file() and str(candidate).startswith(str(FRONTEND_DIST_DIR.resolve())):
                return FileResponse(candidate)
            return FileResponse(FRONTEND_DIST_DIR / "index.html")

    else:

        @app.get("/", include_in_schema=False)
        async def root() -> dict:
            return {
                "message": "Job Agent API is running. Build the frontend (cd frontend && npm run build) to serve the dashboard here.",
                "docs": "/docs",
                "api": "/api/dashboard",
            }

    return app


app = create_app()
