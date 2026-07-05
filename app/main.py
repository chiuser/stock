"""FastAPI entrypoint for the P6S camera management console."""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.routers import attendance, auth, camera, recognition_monitor
from app.services import report_scheduler


@asynccontextmanager
async def lifespan(_: FastAPI):
    await report_scheduler.start_daily_report_scheduler()
    try:
        yield
    finally:
        await report_scheduler.stop_daily_report_scheduler()


app = FastAPI(title="Camera Face Guard", docs_url="/api/docs", lifespan=lifespan)

app.include_router(auth.router, prefix="/api")
app.include_router(camera.router, prefix="/api")
app.include_router(attendance.router, prefix="/api")
app.include_router(recognition_monitor.router, prefix="/api")

_static = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=_static), name="static")


@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def index():
    return RedirectResponse(url="/camera")


@app.get("/login")
def login_page():
    return FileResponse(_static / "login.html")


@app.get("/camera")
def camera_page():
    return FileResponse(_static / "camera.html")


@app.get("/recognition-monitor")
def recognition_monitor_page():
    return FileResponse(_static / "recognition-monitor.html")
