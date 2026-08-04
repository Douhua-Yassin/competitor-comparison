from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .models import ActionCreate, ActionUpdate, ScopeUpdate, TargetCreate
from .service import (
    create_action,
    create_target,
    import_latest_audit,
    list_actions,
    list_targets,
    overview,
    update_action,
    update_scope,
)

ROOT = Path(__file__).resolve().parents[2]
router = APIRouter()
templates = Jinja2Templates(directory=ROOT / "app" / "templates")


@router.get("/reporting", response_class=HTMLResponse)
def reporting_home(request: Request):
    return templates.TemplateResponse(request, "reporting.html", {})


@router.get("/api/reporting/overview")
def api_reporting_overview():
    return overview()


@router.post("/api/reporting/import-latest-audit")
def api_import_latest_audit():
    try:
        return import_latest_audit()
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/api/reporting/scopes")
def api_update_scope(payload: ScopeUpdate):
    try:
        return update_scope(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/reporting/targets")
def api_list_targets(
    product_line_id: Optional[int] = None,
    include_history: bool = False,
):
    return list_targets(product_line_id, include_history)


@router.post("/api/reporting/targets")
def api_create_target(payload: TargetCreate):
    try:
        return create_target(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/reporting/actions")
def api_list_actions(
    product_line_id: Optional[int] = None,
    status: Optional[str] = None,
):
    return list_actions(product_line_id, status)


@router.post("/api/reporting/actions")
def api_create_action(payload: ActionCreate):
    try:
        return create_action(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/api/reporting/actions/{action_id}")
def api_update_action(action_id: int, payload: ActionUpdate):
    try:
        return update_action(action_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
