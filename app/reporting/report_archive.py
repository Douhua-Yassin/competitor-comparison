from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .dashboard_db import DB_PATH, ROOT, WRITE_LOCK, connection


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_report_archive(db_path: Optional[Path] = None) -> None:
    path = Path(db_path or DB_PATH)
    with WRITE_LOCK:
        with connection(path) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS report_runs (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  product_line TEXT NOT NULL,
                  report_type TEXT NOT NULL,
                  period_start TEXT NOT NULL,
                  period_end TEXT NOT NULL,
                  analysis_source TEXT NOT NULL,
                  analysis_warning TEXT,
                  data_snapshot_json TEXT NOT NULL,
                  target_snapshot_json TEXT NOT NULL,
                  note_snapshot_json TEXT NOT NULL,
                  analysis_json TEXT NOT NULL,
                  artifact_path TEXT NOT NULL,
                  artifact_sha256 TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_report_runs_lookup
                  ON report_runs(product_line, report_type, created_at DESC);
                """
            )


def archive_report(
    *,
    product_line: str,
    report_type: str,
    period_start: str,
    period_end: str,
    analysis_source: str,
    analysis_warning: Optional[str],
    data_snapshot: dict[str, Any],
    target_snapshot: list[dict[str, Any]],
    note_snapshot: dict[str, Any],
    analysis: dict[str, Any],
    artifact_path: Path,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    database = Path(db_path or DB_PATH)
    init_report_archive(database)
    artifact = Path(artifact_path).resolve()
    try:
        stored_path = str(artifact.relative_to(ROOT.resolve()))
    except ValueError:
        stored_path = str(artifact)
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    created_at = utc_now()
    with WRITE_LOCK:
        with connection(database) as db:
            cursor = db.execute(
                """
                INSERT INTO report_runs (
                  product_line, report_type, period_start, period_end,
                  analysis_source, analysis_warning, data_snapshot_json,
                  target_snapshot_json, note_snapshot_json, analysis_json,
                  artifact_path, artifact_sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    product_line,
                    report_type,
                    period_start,
                    period_end,
                    analysis_source,
                    analysis_warning,
                    _json(data_snapshot),
                    _json(target_snapshot),
                    _json(note_snapshot),
                    _json(analysis),
                    stored_path,
                    digest,
                    created_at,
                ),
            )
            report_id = int(cursor.lastrowid)
    return {
        "id": report_id,
        "product_line": product_line,
        "report_type": report_type,
        "period_start": period_start,
        "period_end": period_end,
        "analysis_source": analysis_source,
        "analysis_warning": analysis_warning,
        "artifact_path": stored_path,
        "artifact_sha256": digest,
        "created_at": created_at,
    }


def list_report_runs(
    product_line: Optional[str] = None,
    limit: int = 50,
    db_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    database = Path(db_path or DB_PATH)
    init_report_archive(database)
    safe_limit = max(1, min(200, int(limit)))
    with connection(database) as db:
        if product_line:
            rows = db.execute(
                """
                SELECT id, product_line, report_type, period_start, period_end,
                       analysis_source, analysis_warning, artifact_path,
                       artifact_sha256, created_at
                FROM report_runs
                WHERE product_line=?
                ORDER BY id DESC LIMIT ?
                """,
                (product_line, safe_limit),
            ).fetchall()
        else:
            rows = db.execute(
                """
                SELECT id, product_line, report_type, period_start, period_end,
                       analysis_source, analysis_warning, artifact_path,
                       artifact_sha256, created_at
                FROM report_runs
                ORDER BY id DESC LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
    return [dict(row) for row in rows]


def resolve_report_artifact(report_id: int, db_path: Optional[Path] = None) -> Path:
    database = Path(db_path or DB_PATH)
    init_report_archive(database)
    with connection(database) as db:
        row = db.execute(
            "SELECT artifact_path, artifact_sha256 FROM report_runs WHERE id=?",
            (int(report_id),),
        ).fetchone()
    if not row:
        raise ValueError("报告归档不存在")
    stored = Path(str(row["artifact_path"]))
    path = stored if stored.is_absolute() else ROOT / stored
    resolved = path.resolve()
    report_root = (ROOT / "data" / "reports").resolve()
    if report_root not in resolved.parents or not resolved.is_file():
        raise ValueError("报告归档文件不存在或路径无效")
    actual_digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    expected_digest = str(row["artifact_sha256"] or "").strip().lower()
    if not expected_digest or actual_digest.lower() != expected_digest:
        raise ValueError("报告归档文件校验失败，文件可能已被修改")
    return resolved


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
