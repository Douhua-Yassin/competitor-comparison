from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, Optional

from app.lingxing_audit.serializer import extract_records

from .db import (
    DATA_DIR,
    REPORTING_DB_PATH,
    WRITE_LOCK,
    connection,
    init_reporting_db,
    sync_catalog_from_monitor,
    utc_now,
)
from .models import ActionCreate, ActionUpdate, ScopeUpdate, TargetCreate

AUDIT_DIR = DATA_DIR / "lingxing_audit"
SUCCESS_STATES = {"success"}

METRIC_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "orders": {
        "sales_amount": (
            "sales_amount",
            "order_amount",
            "total_amount",
            "revenue",
            "amount",
        ),
        "order_count": ("order_count", "orders", "order_quantity"),
        "units": ("quantity", "sales_quantity", "units", "units_ordered"),
    },
    "after_sales": {
        "refund_amount": ("refund_amount", "return_amount", "amount"),
        "refund_count": ("refund_count", "return_count", "quantity"),
    },
    "fba_inventory": {
        "fba_available": (
            "available",
            "available_quantity",
            "fulfillable_quantity",
            "afn_fulfillable_quantity",
            "stock_available",
        ),
        "fba_inbound": (
            "inbound",
            "inbound_quantity",
            "afn_inbound_receiving_quantity",
            "afn_inbound_shipped_quantity",
        ),
        "fba_reserved": (
            "reserved",
            "reserved_quantity",
            "afn_reserved_quantity",
        ),
        "fba_total": ("total_quantity", "stock", "inventory_quantity"),
    },
    "sp_product_report": {
        "impressions": ("impressions",),
        "clicks": ("clicks",),
        "ad_spend": ("spend", "cost", "advertising_cost"),
        "ad_sales": (
            "sales",
            "attributed_sales",
            "sales_amount",
            "sales_7d",
            "sales_14d",
        ),
        "ad_orders": (
            "orders",
            "attributed_orders",
            "purchases",
            "orders_7d",
            "orders_14d",
        ),
        "ad_units": (
            "units",
            "attributed_units_ordered",
            "units_sold",
        ),
        "ctr": ("ctr", "click_through_rate"),
        "cpc": ("cpc", "cost_per_click"),
        "cvr": ("cvr", "conversion_rate"),
        "acos": ("acos",),
        "roas": ("roas",),
    },
}
# Compatibility for audit files produced by early development builds.
METRIC_ALIASES["sp_product_reports"] = METRIC_ALIASES["sp_product_report"]

DATE_KEYS = (
    "date",
    "report_date",
    "stat_date",
    "data_date",
    "day",
    "start_date",
)
ASIN_KEYS = ("asin", "child_asin", "parent_asin", "item_asin")
SKU_KEYS = ("sku", "seller_sku", "msku", "local_sku")


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _row_dict(row: Any) -> dict[str, Any]:
    return dict(row) if row is not None else {}


def _ensure_line(db, product_line_id: int) -> None:
    row = db.execute(
        "SELECT id FROM report_product_lines WHERE id=? AND active=1",
        (product_line_id,),
    ).fetchone()
    if row is None:
        raise ValueError("产品线不存在或已停用")


def _ensure_product(db, product_line_id: int, asin: Optional[str]) -> None:
    if not asin:
        return
    row = db.execute(
        """
        SELECT id FROM report_products
        WHERE product_line_id=? AND asin=? AND active=1 AND is_self=1
        """,
        (product_line_id, asin),
    ).fetchone()
    if row is None:
        raise ValueError("该我方 ASIN 不属于当前产品线")


def overview(db_path: Optional[Path] = None) -> dict[str, Any]:
    path = Path(db_path or REPORTING_DB_PATH)
    init_reporting_db(path)
    sync_catalog_from_monitor(path)
    with connection(path) as db:
        lines = [
            dict(row)
            for row in db.execute(
                """
                SELECT rpl.*,
                       (SELECT COUNT(*) FROM report_products rp
                        WHERE rp.product_line_id=rpl.id AND rp.active=1 AND rp.is_self=1) AS product_count,
                       (SELECT COUNT(*) FROM targets t
                        WHERE t.product_line_id=rpl.id AND t.status='active') AS target_count,
                       (SELECT COUNT(*) FROM action_log a
                        WHERE a.product_line_id=rpl.id
                          AND a.status IN ('planned','in_progress')) AS open_action_count
                FROM report_product_lines rpl
                WHERE rpl.active=1
                ORDER BY rpl.sheet_order, rpl.id
                """
            )
        ]
        for line in lines:
            line["products"] = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT id, asin, brand, size_normalized, is_self,
                           active, responsibility_level,
                           COALESCE(responsibility_level, ?) AS effective_responsibility_level
                    FROM report_products
                    WHERE product_line_id=? AND active=1 AND is_self=1
                    ORDER BY brand, asin
                    """,
                    (line["responsibility_level"], line["id"]),
                )
            ]
        availability = [
            dict(row)
            for row in db.execute(
                """
                SELECT endpoint_key, category, label, status, message, updated_at
                FROM endpoint_availability
                ORDER BY category, endpoint_key
                """
            )
        ]
        last_run = _row_dict(
            db.execute(
                """
                SELECT id, run_type, source_run_id, started_at, finished_at,
                       status, summary_json, created_at
                FROM report_runs
                ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
        )
        if last_run:
            last_run["summary"] = json.loads(last_run.pop("summary_json") or "{}")
        metric_count = db.execute("SELECT COUNT(*) FROM daily_metrics").fetchone()[0]
        snapshot_count = db.execute("SELECT COUNT(*) FROM raw_snapshots").fetchone()[0]
    return {
        "product_lines": lines,
        "availability": availability,
        "last_import": last_run or None,
        "metric_count": metric_count,
        "snapshot_count": snapshot_count,
    }


def update_scope(payload: ScopeUpdate, db_path: Optional[Path] = None) -> dict[str, Any]:
    path = Path(db_path or REPORTING_DB_PATH)
    init_reporting_db(path)
    now = utc_now()
    with WRITE_LOCK:
        with connection(path) as db:
            _ensure_line(db, payload.product_line_id)
            if payload.asin:
                _ensure_product(db, payload.product_line_id, payload.asin)
                level = None if payload.responsibility_level == "inherit" else payload.responsibility_level
                db.execute(
                    """
                    UPDATE report_products
                    SET responsibility_level=?, updated_at=?
                    WHERE product_line_id=? AND asin=?
                    """,
                    (level, now, payload.product_line_id, payload.asin),
                )
            else:
                if payload.responsibility_level == "inherit":
                    raise ValueError("产品线不能使用继承档位")
                db.execute(
                    """
                    UPDATE report_product_lines
                    SET responsibility_level=?, updated_at=?
                    WHERE id=?
                    """,
                    (payload.responsibility_level, now, payload.product_line_id),
                )
    return payload.model_dump()


def create_target(payload: TargetCreate, db_path: Optional[Path] = None) -> dict[str, Any]:
    path = Path(db_path or REPORTING_DB_PATH)
    init_reporting_db(path)
    now = utc_now()
    start = payload.period_start.isoformat()
    end = payload.period_end.isoformat()
    with WRITE_LOCK:
        with connection(path) as db:
            _ensure_line(db, payload.product_line_id)
            _ensure_product(db, payload.product_line_id, payload.asin)
            params = (
                payload.product_line_id,
                payload.asin,
                payload.asin,
                payload.period_type,
                start,
                end,
                payload.metric_code,
            )
            version = int(
                db.execute(
                    """
                    SELECT COALESCE(MAX(version), 0) + 1
                    FROM targets
                    WHERE product_line_id=?
                      AND ((asin IS NULL AND ? IS NULL) OR asin=?)
                      AND period_type=? AND period_start=? AND period_end=?
                      AND metric_code=?
                    """,
                    params,
                ).fetchone()[0]
            )
            db.execute(
                """
                UPDATE targets SET status='superseded', updated_at=?
                WHERE product_line_id=?
                  AND ((asin IS NULL AND ? IS NULL) OR asin=?)
                  AND period_type=? AND period_start=? AND period_end=?
                  AND metric_code=? AND status='active'
                """,
                (now,) + params,
            )
            cursor = db.execute(
                """
                INSERT INTO targets (
                  period_type, period_start, period_end, product_line_id,
                  asin, metric_code, target_value, unit, version, status,
                  note, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (
                    payload.period_type,
                    start,
                    end,
                    payload.product_line_id,
                    payload.asin,
                    payload.metric_code,
                    payload.target_value,
                    payload.unit,
                    version,
                    payload.note,
                    now,
                    now,
                ),
            )
            row = db.execute(
                "SELECT * FROM targets WHERE id=?", (cursor.lastrowid,)
            ).fetchone()
    return dict(row)


def list_targets(
    product_line_id: Optional[int] = None,
    include_history: bool = False,
    db_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    path = Path(db_path or REPORTING_DB_PATH)
    init_reporting_db(path)
    clauses = []
    params: list[Any] = []
    if product_line_id is not None:
        clauses.append("t.product_line_id=?")
        params.append(product_line_id)
    if not include_history:
        clauses.append("t.status='active'")
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with connection(path) as db:
        return [
            dict(row)
            for row in db.execute(
                """
                SELECT t.*, l.name AS product_line_name
                FROM targets t
                JOIN report_product_lines l ON l.id=t.product_line_id
                """
                + where
                + " ORDER BY t.period_start DESC, l.sheet_order, t.metric_code, t.version DESC",
                params,
            )
        ]


def create_action(payload: ActionCreate, db_path: Optional[Path] = None) -> dict[str, Any]:
    path = Path(db_path or REPORTING_DB_PATH)
    init_reporting_db(path)
    now = utc_now()
    with WRITE_LOCK:
        with connection(path) as db:
            _ensure_line(db, payload.product_line_id)
            _ensure_product(db, payload.product_line_id, payload.asin)
            cursor = db.execute(
                """
                INSERT INTO action_log (
                  product_line_id, asin, action_date, action_type, title,
                  content, reason, expected_result, review_date, status,
                  actual_result, source, confirmed, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.product_line_id,
                    payload.asin,
                    payload.action_date.isoformat(),
                    payload.action_type.strip(),
                    payload.title.strip(),
                    payload.content.strip(),
                    payload.reason,
                    payload.expected_result,
                    payload.review_date.isoformat() if payload.review_date else None,
                    payload.status,
                    payload.actual_result,
                    payload.source,
                    1 if payload.confirmed else 0,
                    now,
                    now,
                ),
            )
            row = db.execute(
                "SELECT * FROM action_log WHERE id=?", (cursor.lastrowid,)
            ).fetchone()
    return dict(row)


def update_action(
    action_id: int,
    payload: ActionUpdate,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    path = Path(db_path or REPORTING_DB_PATH)
    init_reporting_db(path)
    changes = payload.model_dump(exclude_unset=True)
    if "review_date" in changes and changes["review_date"] is not None:
        changes["review_date"] = changes["review_date"].isoformat()
    if "confirmed" in changes and changes["confirmed"] is not None:
        changes["confirmed"] = 1 if changes["confirmed"] else 0
    if not changes:
        with connection(path) as db:
            row = db.execute("SELECT * FROM action_log WHERE id=?", (action_id,)).fetchone()
            if row is None:
                raise ValueError("行动记录不存在")
            return dict(row)
    changes["updated_at"] = utc_now()
    assignments = ", ".join(f"{key}=?" for key in changes)
    with WRITE_LOCK:
        with connection(path) as db:
            cursor = db.execute(
                f"UPDATE action_log SET {assignments} WHERE id=?",
                list(changes.values()) + [action_id],
            )
            if cursor.rowcount == 0:
                raise ValueError("行动记录不存在")
            row = db.execute("SELECT * FROM action_log WHERE id=?", (action_id,)).fetchone()
    return dict(row)


def list_actions(
    product_line_id: Optional[int] = None,
    status: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    path = Path(db_path or REPORTING_DB_PATH)
    init_reporting_db(path)
    clauses = []
    params: list[Any] = []
    if product_line_id is not None:
        clauses.append("a.product_line_id=?")
        params.append(product_line_id)
    if status:
        clauses.append("a.status=?")
        params.append(status)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with connection(path) as db:
        return [
            dict(row)
            for row in db.execute(
                """
                SELECT a.*, l.name AS product_line_name
                FROM action_log a
                JOIN report_product_lines l ON l.id=a.product_line_id
                """
                + where
                + " ORDER BY a.action_date DESC, a.id DESC",
                params,
            )
        ]


def import_latest_audit(
    db_path: Optional[Path] = None,
    audit_dir: Optional[Path] = None,
) -> dict[str, Any]:
    path = Path(db_path or REPORTING_DB_PATH)
    output_dir = Path(audit_dir or AUDIT_DIR)
    init_reporting_db(path)
    latest_file = output_dir / "latest.txt"
    if not latest_file.exists():
        raise FileNotFoundError("未找到领星接口盘点 latest.txt")
    run_id = latest_file.read_text(encoding="utf-8-sig").strip()
    if not run_id:
        raise ValueError("领星接口盘点 latest.txt 为空")
    run_dir = output_dir / run_id
    report_path = run_dir / "audit-report.json"
    if not report_path.exists():
        raise FileNotFoundError(f"未找到 {report_path}")
    report = json.loads(report_path.read_text(encoding="utf-8-sig"))

    now = utc_now()
    with WRITE_LOCK:
        with connection(path) as db:
            existing = db.execute(
                "SELECT id FROM report_runs WHERE run_type='lingxing_audit' AND source_run_id=?",
                (run_id,),
            ).fetchone()
            if existing:
                return {
                    "imported": False,
                    "reason": "already_imported",
                    "run_id": run_id,
                    "report_run_id": existing["id"],
                }
            cursor = db.execute(
                """
                INSERT INTO report_runs (
                  run_type, source_run_id, started_at, finished_at,
                  status, summary_json, created_at
                ) VALUES ('lingxing_audit', ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    report.get("started_at"),
                    report.get("finished_at"),
                    _overall_status(report.get("summary") or {}),
                    _json_text(report.get("summary") or {}),
                    now,
                ),
            )
            report_run_id = int(cursor.lastrowid)
            imported_snapshots = 0
            imported_metrics = 0
            for result in report.get("results") or []:
                endpoint_key = str(result.get("key") or "unknown")
                status = str(result.get("status") or "unknown")
                payload = _load_sample_payload(run_dir, endpoint_key, result)
                payload_text = _json_text(payload) if payload is not None else None
                payload_hash = (
                    hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
                    if payload_text is not None
                    else None
                )
                sample_file = result.get("sample_file")
                snapshot_cursor = db.execute(
                    """
                    INSERT INTO raw_snapshots (
                      run_id, endpoint_key, category, label, status,
                      sample_count, captured_at, payload_json, payload_sha256,
                      sample_file, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        report_run_id,
                        endpoint_key,
                        result.get("category"),
                        result.get("label"),
                        status,
                        result.get("sample_count"),
                        report.get("finished_at") or now,
                        payload_text,
                        payload_hash,
                        str(sample_file) if sample_file else None,
                        result.get("message"),
                    ),
                )
                snapshot_id = int(snapshot_cursor.lastrowid)
                imported_snapshots += 1
                db.execute(
                    """
                    INSERT INTO endpoint_availability (
                      endpoint_key, category, label, status, message,
                      last_run_id, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(endpoint_key) DO UPDATE SET
                      category=excluded.category,
                      label=excluded.label,
                      status=excluded.status,
                      message=excluded.message,
                      last_run_id=excluded.last_run_id,
                      updated_at=excluded.updated_at
                    """,
                    (
                        endpoint_key,
                        result.get("category"),
                        result.get("label"),
                        status,
                        result.get("message"),
                        report_run_id,
                        now,
                    ),
                )
                if status in SUCCESS_STATES and payload is not None:
                    imported_metrics += _normalize_metrics(
                        db,
                        endpoint_key,
                        payload,
                        snapshot_id,
                        report.get("finished_at") or now,
                    )
    return {
        "imported": True,
        "run_id": run_id,
        "report_run_id": report_run_id,
        "snapshots": imported_snapshots,
        "metrics": imported_metrics,
        "summary": report.get("summary") or {},
    }


def _overall_status(summary: dict[str, Any]) -> str:
    if summary.get("success") and len(summary) == 1:
        return "success"
    if summary.get("success"):
        return "partial_success"
    return "failed"


def _load_sample_payload(run_dir: Path, endpoint_key: str, result: dict[str, Any]) -> Any:
    candidates = [run_dir / "samples" / f"{endpoint_key}.json"]
    sample_file = result.get("sample_file")
    if sample_file:
        sample_path = Path(str(sample_file))
        candidates.append(sample_path if sample_path.is_absolute() else run_dir / sample_path)
    for candidate in candidates:
        if candidate.exists():
            try:
                return json.loads(candidate.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
    return None


def _normalize_metrics(
    db,
    endpoint_key: str,
    payload: Any,
    snapshot_id: int,
    captured_at: str,
) -> int:
    aliases = METRIC_ALIASES.get(endpoint_key)
    if not aliases:
        return 0
    records = extract_records(payload)
    inserted = 0
    fallback_date = str(captured_at)[:10] or date.today().isoformat()
    for record in records:
        if not isinstance(record, dict):
            continue
        lowered = {str(key).lower(): value for key, value in record.items()}
        metric_date = _first_text(lowered, DATE_KEYS) or fallback_date
        metric_date = metric_date[:10]
        asin = (_first_text(lowered, ASIN_KEYS) or "").upper() or None
        sku = _first_text(lowered, SKU_KEYS)
        line_ids = _line_ids_for_asin(db, asin)
        if not line_ids:
            line_ids = [None]
        dimensions = {
            key: value
            for key, value in record.items()
            if str(key).lower() in {"sid", "profile_id", "campaign_id", "ad_group_id", "currency"}
        }
        for metric_code, keys in aliases.items():
            value = _first_number(lowered, keys)
            if value is None:
                continue
            for product_line_id in line_ids:
                db.execute(
                    """
                    INSERT INTO daily_metrics (
                      metric_date, product_line_id, asin, sku, metric_code,
                      metric_value, unit, source_endpoint, source_snapshot_id,
                      dimensions_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        metric_date,
                        product_line_id,
                        asin,
                        sku,
                        metric_code,
                        value,
                        _metric_unit(metric_code),
                        endpoint_key,
                        snapshot_id,
                        _json_text(dimensions),
                        utc_now(),
                    ),
                )
                inserted += 1
    return inserted


def _line_ids_for_asin(db, asin: Optional[str]) -> list[int]:
    if not asin:
        return []
    return [
        int(row[0])
        for row in db.execute(
            """
            SELECT product_line_id FROM report_products
            WHERE asin=? AND active=1 AND is_self=1
            ORDER BY product_line_id
            """,
            (asin,),
        )
    ]


def _first_text(record: dict[str, Any], keys: tuple[str, ...]) -> Optional[str]:
    for key in keys:
        value = record.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _first_number(record: dict[str, Any], keys: tuple[str, ...]) -> Optional[float]:
    for key in keys:
        value = record.get(key)
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip().replace(",", "").replace("%", "")
        if not text:
            continue
        try:
            number = float(text)
            if "%" in str(value):
                number /= 100
            return number
        except ValueError:
            continue
    return None


def _metric_unit(metric_code: str) -> Optional[str]:
    if metric_code in {"sales_amount", "refund_amount", "ad_spend", "ad_sales", "cpc"}:
        return "currency"
    if metric_code in {"ctr", "cvr", "acos"}:
        return "ratio"
    if metric_code == "roas":
        return "multiple"
    return "count"
