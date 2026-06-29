"""FastAPI entrypoint for the P6S camera management console."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.routers import auth, camera

app = FastAPI(title="Camera Face Guard", docs_url="/api/docs")

app.include_router(auth.router, prefix="/api")
app.include_router(camera.router, prefix="/api")

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
