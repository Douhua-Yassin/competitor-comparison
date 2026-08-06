from __future__ import annotations

from datetime import date
from pathlib import Path

from openpyxl import Workbook

from app.reporting.dashboard_db import (
    list_settings_products,
    update_listing_scope,
    upsert_daily_metric,
    upsert_listings,
    upsert_stores,
)
from app.reporting.dashboard_service import report_context
from app.reporting.targets import import_targets


def test_week_report_uses_monday_to_current_day_and_week_target(tmp_path: Path):
    db_path = tmp_path / "reporting.db"
    upsert_stores([{"sid": 10, "name": "美国店", "country": "美国"}], db_path)
    upsert_listings(
        [{"sid": 10, "asin": "B000TEST01", "msku": "GOAL-01", "product_name": "足球门", "country": "美国", "status": 1}],
        db_path,
    )
    product = list_settings_products(db_path)["products"][0]
    update_listing_scope(product["id"], "key", "足球门", db_path)
    for metric_date, sales in (
        ("2026-08-02", 900),
        ("2026-08-03", 100),
        ("2026-08-04", 200),
        ("2026-08-05", 300),
        ("2026-08-06", 400),
    ):
        upsert_daily_metric(metric_date, product["id"], "sales_amount", sales, "currency", "orders", db_path=db_path)

    target_path = tmp_path / "目标表.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "目标"
    sheet.append([
        "周期类型", "周期", "产品线", "店铺SID", "ASIN", "MSKU",
        "销售额目标", "销量目标", "利润目标", "利润率目标",
        "TACOS目标", "广告花费目标", "FBA可售库存目标", "备注",
    ])
    sheet.append(["周", "2026-W32", "足球门", "", "", "", 2000, "", "", "", "", "", "", "自然周目标"])
    workbook.save(target_path)
    import_targets(target_path, db_path)

    _, selected = report_context("足球门", "week", db_path, date(2026, 8, 6))
    assert selected["start"] == "2026-08-03"
    assert selected["end"] == "2026-08-06"
    assert selected["summary"]["sales_amount"] == 1000
    target = next(item for item in selected["targets"] if item["metric_code"] == "sales_amount")
    assert target["target"] == 2000
    assert target["completion"] == 0.5
