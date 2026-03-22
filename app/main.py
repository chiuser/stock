import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse

from app.routers import stocks
from app.routers import auth
from app.routers import portfolio
from app.routers import admin

app = FastAPI(title="Stock Charts", docs_url="/api/docs")

app.include_router(stocks.router,    prefix="/api")
app.include_router(auth.router,      prefix="/api")
app.include_router(portfolio.router, prefix="/api")
app.include_router(admin.router,     prefix="/api")

_static = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=_static), name="static")


@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def index():
    return RedirectResponse(url="/portfolio")


@app.get("/login")
def login_page():
    return FileResponse(os.path.join(_static, "login.html"))


@app.get("/portfolio")
def portfolio_page():
    return FileResponse(os.path.join(_static, "portfolio.html"))


@app.get("/chart")
def chart_page():
    return FileResponse(os.path.join(_static, "chart.html"))


@app.get("/admin")
def admin_page():
    return FileResponse(os.path.join(_static, "admin.html"))
