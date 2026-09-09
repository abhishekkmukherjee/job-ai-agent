from __future__ import annotations

from fastapi import APIRouter

from . import applications, dashboard, jobs, profile, runs, settings

api_router = APIRouter()
api_router.include_router(dashboard.router)
api_router.include_router(jobs.router)
api_router.include_router(applications.router)
api_router.include_router(profile.router)
api_router.include_router(settings.router)
api_router.include_router(runs.router)
