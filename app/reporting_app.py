from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.reporting.dashboard_db import init_dashboard_db
from app.reporting.dashboard_routes import router as reporting_router
from app.reporting.report_archive import init_report_archive
from app.reporting.targets import init_targets_db

ROOT = Path(__file__).resolve().parents[1]


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_dashboard_db()
    init_targets_db()
    init_report_archive()
    yield


app = FastAPI(title="经营报告", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "app" / "static"), name="static")
app.include_router(reporting_router)


@app.middleware("http")
async def local_runtime_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/reporting") or path.startswith("/api/reporting") or path.startswith("/static/reporting-"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    response.headers["X-Reporting-Service"] = "local-8790"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/", include_in_schema=False)
def root_redirect():
    return RedirectResponse(url="/reporting")


@app.get("/api/status")
def status():
    return {"service": "reporting", "status": "ready", "source": "lingxing"}
