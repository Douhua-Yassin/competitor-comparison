from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from .dashboard_db import list_settings_products, save_note, update_listing_scope
from .dashboard_models import ListingScopeUpdate, NoteSave
from .dashboard_service import dashboard
from .lingxing_sync import run_recent_sync, sync_status
from .report_generator import generate_report

ROOT = Path(__file__).resolve().parents[2]
router = APIRouter()
templates = Jinja2Templates(directory=ROOT / "app" / "templates")


@router.get("/reporting", response_class=HTMLResponse)
def reporting_home(request: Request):
    return templates.TemplateResponse(request, "reporting_dashboard.html", {})


@router.get("/reporting/settings", response_class=HTMLResponse)
def reporting_settings(request: Request):
    return templates.TemplateResponse(request, "reporting_settings.html", {})


@router.get("/api/reporting/dashboard")
def api_dashboard():
    return dashboard()


@router.get("/api/reporting/products")
def api_products():
    return list_settings_products()


@router.put("/api/reporting/products/scope")
def api_update_product_scope(payload: ListingScopeUpdate):
    try:
        return update_listing_scope(
            payload.listing_id,
            payload.responsibility_level,
            payload.product_line,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/reporting/sync")
async def api_start_sync():
    state = sync_status()
    if state["running"]:
        raise HTTPException(status_code=409, detail="领星数据同步正在运行")

    async def worker() -> None:
        try:
            await run_recent_sync()
        except Exception:
            # Detailed sanitized error is retained in sync_status and lx_sync_runs.
            pass

    asyncio.create_task(worker())
    return {"started": True, "window_days": 14}


@router.get("/api/reporting/sync-status")
def api_sync_status():
    return sync_status()


@router.put("/api/reporting/notes")
def api_save_note(payload: NoteSave):
    try:
        return save_note(
            payload.product_line,
            payload.window_code,
            payload.period_key,
            payload.content,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/reporting/reports/{report_type}")
def api_generate_report(product_line: str, report_type: str):
    try:
        path = generate_report(product_line, report_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    filename = path.name
    return FileResponse(
        path,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        filename=filename,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )
