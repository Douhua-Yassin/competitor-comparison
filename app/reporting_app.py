from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.reporting.db import init_reporting_db
from app.reporting.routes import router as reporting_router

ROOT = Path(__file__).resolve().parents[1]


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_reporting_db()
    yield


app = FastAPI(title="经营报告数据管理", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "app" / "static"), name="static")
app.include_router(reporting_router)


@app.get("/", include_in_schema=False)
def root_redirect():
    return RedirectResponse(url="/reporting")


@app.get("/api/status")
def status():
    return {"service": "reporting", "status": "ready"}
