"""
FastAPI entrypoint for the AI Cycling Coach Databricks App.
Serves the React SPA from ../frontend/dist/ and mounts all API routers.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from routers.chat import router as chat_router
from routers.dashboard import router as dashboard_router
from routers.activities import router as activities_router
from routers.plan import router as plan_router
from routers.insights import router as insights_router
from routers.performance import router as performance_router

app = FastAPI(title="AI Cycling Coach", docs_url="/api/docs", redoc_url=None)

# Allow Vite dev server to call the API during local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routers
app.include_router(chat_router)
app.include_router(dashboard_router)
app.include_router(activities_router)
app.include_router(plan_router)
app.include_router(insights_router)
app.include_router(performance_router)

# Serve built React frontend
DIST = Path(__file__).parent.parent / "frontend" / "dist"

if DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        """Return index.html for all non-API routes (React Router)."""
        index = DIST / "index.html"
        return FileResponse(index)
