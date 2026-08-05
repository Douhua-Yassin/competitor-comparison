from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.reporting.dashboard_db import init_dashboard_db
from app.reporting.dashboard_routes import router as reporting_router

ROOT = Path(__file__).resolve().parents[1]


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_dashboard_db()
    yield


app = FastAPI(title="经营报告", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "app" / "static"), name="static")
app.include_router(reporting_router)


@app.get("/", include_in_schema=False)
def root_redirect():
    return RedirectResponse(url="/reporting")


@app.get("/api/status")
def status():
    return {"service": "reporting", "status": "ready", "source": "lingxing"}
