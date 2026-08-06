from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from app.lingxing_audit.config import AuditSettings

from .dashboard_db import DB_PATH, connection, list_settings_products, save_note, update_listing_scope
from .dashboard_models import ListingScopeUpdate, NoteSave
from .dashboard_service import dashboard
from .lingxing_sync import (
    cancel_sync_reservation,
    reserve_sync_start,
    run_recent_sync,
    sync_status,
)
from .report_archive import list_report_runs, resolve_report_artifact
from .report_generator import generate_report
from .targets import import_targets, target_status, write_target_template

ROOT = Path(__file__).resolve().parents[2]
router = APIRouter()
templates = Jinja2Templates(directory=ROOT / "app" / "templates")
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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


@router.get("/api/reporting/targets/status")
def api_target_status():
    return target_status()


@router.post("/api/reporting/targets/import")
def api_import_targets():
    try:
        return import_targets()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/reporting/targets/template")
def api_target_template():
    path = write_target_template(ROOT / "data" / "templates" / "目标表模板.xlsx")
    return FileResponse(
        path,
        media_type=XLSX_MEDIA_TYPE,
        filename=path.name,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(path.name)}"},
    )


@router.get("/api/reporting/reports/history")
def api_report_history(product_line: str | None = None, limit: int = 50):
    return {"reports": list_report_runs(product_line, limit)}


@router.get("/api/reporting/reports/archive/{report_id}")
def api_report_archive(report_id: int):
    try:
        path = resolve_report_artifact(report_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type=DOCX_MEDIA_TYPE,
        filename=path.name,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(path.name)}"},
    )


@router.get("/api/reporting/diagnostics")
def api_diagnostics():
    database_ok = False
    database_error = None
    try:
        with connection() as db:
            db.execute("SELECT 1").fetchone()
        database_ok = True
    except Exception as exc:  # pragma: no cover - operating-system dependent
        database_error = f"{type(exc).__name__}: {exc}"

    lingxing_configured = False
    lingxing_config_error = None
    try:
        settings = AuditSettings.load()
        lingxing_configured = bool(settings.app_id and settings.app_secret and settings.base_url)
    except Exception as exc:
        lingxing_config_error = type(exc).__name__

    proxy_names = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
    active_proxy_variables = sorted(name for name in proxy_names if os.environ.get(name))
    no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    no_proxy_items = {item.strip().lower() for item in no_proxy.split(",") if item.strip()}

    return {
        "service": "reporting",
        "status": "ready",
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "database": {
            "path": str(DB_PATH),
            "exists": DB_PATH.exists(),
            "readable": database_ok,
            "error": database_error,
        },
        "lingxing": {
            "configured": lingxing_configured,
            "config_error": lingxing_config_error,
        },
        "targets": target_status(),
        "proxy": {
            "active_environment_variables": active_proxy_variables,
            "loopback_bypassed": "127.0.0.1" in no_proxy_items and "localhost" in no_proxy_items,
        },
        "browser": {
            "launch_mode": "isolated-direct",
            "extensions_disabled": True,
        },
    }


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
    if not reserve_sync_start():
        raise HTTPException(status_code=409, detail="领星数据同步正在运行")

    async def worker() -> None:
        try:
            await run_recent_sync()
        except Exception:
            # Detailed sanitized error is retained in sync_status and lx_sync_runs.
            pass

    try:
        asyncio.create_task(worker())
    except Exception:
        cancel_sync_reservation()
        raise
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
        media_type=DOCX_MEDIA_TYPE,
        filename=filename,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )
