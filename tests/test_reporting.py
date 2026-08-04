from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

from app.reporting.db import connection, init_reporting_db, utc_now
from app.reporting.models import ActionCreate, ActionUpdate, ScopeUpdate, TargetCreate
from app.reporting.service import (
    create_action,
    create_target,
    import_latest_audit,
    list_actions,
    list_targets,
    overview,
    update_action,
    update_scope,
)


def seed_catalog(db_path: Path) -> int:
    init_reporting_db(db_path, db_path.parent / "missing-monitor.db")
    now = utc_now()
    with connection(db_path) as db:
        cursor = db.execute(
            """
            INSERT INTO report_product_lines (
              monitor_line_id, name, sheet_order, active,
              responsibility_level, created_at, updated_at
            ) VALUES (1, '打击笼', 0, 1, 'normal', ?, ?)
            """,
            (now, now),
        )
        line_id = int(cursor.lastrowid)
        db.execute(
            """
            INSERT INTO report_products (
              product_line_id, asin, brand, size_normalized,
              is_self, active, created_at, updated_at
            ) VALUES (?, 'B0D3D2W989', 'TEST', '13 ft', 1, 1, ?, ?)
            """,
            (line_id, now, now),
        )
    return line_id


def test_scope_and_target_versions_are_persisted(tmp_path: Path):
    db_path = tmp_path / "reporting.db"
    line_id = seed_catalog(db_path)

    result = update_scope(
        ScopeUpdate(product_line_id=line_id, responsibility_level="key"),
        db_path,
    )
    assert result["responsibility_level"] == "key"

    payload = TargetCreate(
        period_type="month",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        product_line_id=line_id,
        metric_code="sales_amount",
        target_value=10000,
        unit="USD",
    )
    first = create_target(payload, db_path)
    second = create_target(payload.model_copy(update={"target_value": 12000}), db_path)

    assert first["version"] == 1
    assert second["version"] == 2
    active = list_targets(line_id, False, db_path)
    history = list_targets(line_id, True, db_path)
    assert len(active) == 1
    assert active[0]["target_value"] == 12000
    assert [item["status"] for item in history] == ["active", "superseded"]


def test_action_lifecycle_keeps_reason_and_result(tmp_path: Path):
    db_path = tmp_path / "reporting.db"
    line_id = seed_catalog(db_path)
    created = create_action(
        ActionCreate(
            product_line_id=line_id,
            asin="B0D3D2W989",
            action_date=date(2026, 8, 4),
            action_type="pricing",
            title="降低引流款价格",
            content="将引流款价格下调两美元",
            reason="恢复转化率",
            expected_result="三日内转化率回升",
            review_date=date(2026, 8, 7),
        ),
        db_path,
    )
    updated = update_action(
        created["id"],
        ActionUpdate(status="completed", actual_result="销量回升，利润率下降可控"),
        db_path,
    )
    assert updated["status"] == "completed"
    assert "销量回升" in updated["actual_result"]
    rows = list_actions(line_id, "completed", db_path)
    assert rows[0]["reason"] == "恢复转化率"


def test_import_latest_audit_keeps_failures_and_normalizes_metrics(tmp_path: Path):
    db_path = tmp_path / "reporting.db"
    line_id = seed_catalog(db_path)
    audit_dir = tmp_path / "lingxing_audit"
    run_id = "20260804-174447"
    run_dir = audit_dir / run_id
    sample_dir = run_dir / "samples"
    sample_dir.mkdir(parents=True)
    (audit_dir / "latest.txt").write_text(run_id, encoding="utf-8")

    report = {
        "run_id": run_id,
        "started_at": "2026-08-04T09:44:47+00:00",
        "finished_at": "2026-08-04T09:45:08+00:00",
        "summary": {"success": 2, "permission_denied": 1},
        "results": [
            {
                "key": "fba_inventory",
                "category": "库存",
                "label": "FBA库存",
                "status": "success",
                "sample_count": 1,
            },
            {
                "key": "sp_product_reports",
                "category": "广告",
                "label": "SP商品广告报表",
                "status": "success",
                "sample_count": 1,
            },
            {
                "key": "income_statement_asins",
                "category": "利润",
                "label": "ASIN利润报表",
                "status": "permission_denied",
                "message": "403 授权失效",
            },
        ],
    }
    (run_dir / "audit-report.json").write_text(
        json.dumps(report, ensure_ascii=False), encoding="utf-8"
    )
    (sample_dir / "fba_inventory.json").write_text(
        json.dumps(
            {
                "data": [
                    {
                        "asin": "B0D3D2W989",
                        "report_date": "2026-08-03",
                        "available_quantity": 18,
                        "inbound_quantity": 20,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (sample_dir / "sp_product_reports.json").write_text(
        json.dumps(
            {
                "data": [
                    {
                        "asin": "B0D3D2W989",
                        "date": "2026-08-03",
                        "impressions": 1000,
                        "clicks": 20,
                        "spend": 15.5,
                        "sales": 80,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    imported = import_latest_audit(db_path, audit_dir)
    assert imported["imported"] is True
    assert imported["snapshots"] == 3
    assert imported["metrics"] >= 6

    second = import_latest_audit(db_path, audit_dir)
    assert second["imported"] is False
    assert second["reason"] == "already_imported"

    data = overview(db_path)
    assert data["last_import"]["status"] == "partial_success"
    assert data["metric_count"] == imported["metrics"]
    availability = {item["endpoint_key"]: item for item in data["availability"]}
    assert availability["income_statement_asins"]["status"] == "permission_denied"

    with sqlite3.connect(db_path) as db:
        mapped = db.execute(
            """
            SELECT COUNT(*) FROM daily_metrics
            WHERE product_line_id=? AND asin='B0D3D2W989'
            """,
            (line_id,),
        ).fetchone()[0]
    assert mapped == imported["metrics"]
