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
from app.reporting.dashboard_service import dashboard
from app.reporting.targets import import_targets, target_status, targets_for_period


HEADERS = [
    "周期类型", "周期", "产品线", "店铺SID", "ASIN", "MSKU",
    "销售额目标", "销量目标", "利润目标", "利润率目标",
    "TACOS目标", "广告花费目标", "FBA可售库存目标", "备注",
]


def _write_targets(path: Path, sales_target: float = 50000) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "目标"
    sheet.append(HEADERS)
    sheet.append(["月", "2026-08", "足球门", "", "", "", sales_target, 600, "", "", "12%", 7000, 300, "月目标"])
    workbook.save(path)


def test_target_import_is_versioned_and_visible_on_month_dashboard(tmp_path: Path):
    db_path = tmp_path / "reporting.db"
    target_path = tmp_path / "目标表.xlsx"
    _write_targets(target_path)

    first = import_targets(target_path, db_path)
    assert first["imported"] is True
    assert first["row_count"] == 5
    duplicate = import_targets(target_path, db_path)
    assert duplicate["duplicate"] is True

    upsert_stores([{"sid": 10, "name": "美国店", "country": "美国"}], db_path)
    upsert_listings(
        [{"sid": 10, "asin": "B000TEST01", "msku": "GOAL-01", "product_name": "足球门", "country": "美国", "status": 1}],
        db_path,
    )
    product = list_settings_products(db_path)["products"][0]
    update_listing_scope(product["id"], "key", "足球门", db_path)
    for day, sales, units in ((1, 1000, 10), (2, 1500, 15), (3, 2000, 20), (4, 2500, 25)):
        metric_date = f"2026-08-{day:02d}"
        upsert_daily_metric(metric_date, product["id"], "sales_amount", sales, "currency", "orders", db_path=db_path)
        upsert_daily_metric(metric_date, product["id"], "units", units, "count", "orders", db_path=db_path)

    data = dashboard(db_path, date(2026, 8, 4))
    month = next(item for item in data["product_lines"][0]["windows"] if item["code"] == "month")
    sales_target = next(item for item in month["targets"] if item["metric_code"] == "sales_amount")
    assert sales_target["actual"] == 7000
    assert sales_target["target"] == 50000
    assert round(sales_target["completion"], 2) == 0.14
    assert sales_target["status"] == "in_progress"

    _write_targets(target_path, sales_target=60000)
    second = import_targets(target_path, db_path)
    assert second["imported"] is True
    targets = targets_for_period("足球门", "month", "2026-08-01", "2026-08-04", month["summary"], db_path)
    revised = next(item for item in targets if item["metric_code"] == "sales_amount")
    assert revised["target"] == 60000
    assert target_status(db_path)["active_target_count"] == 5


def test_listing_target_uses_only_matching_listing_actual(tmp_path: Path):
    db_path = tmp_path / "reporting.db"
    upsert_stores([{"sid": 10, "name": "美国店", "country": "美国"}], db_path)
    upsert_listings(
        [
            {"sid": 10, "asin": "B000TEST01", "msku": "GOAL-01", "product_name": "足球门6x4", "country": "美国", "status": 1},
            {"sid": 10, "asin": "B000TEST02", "msku": "GOAL-02", "product_name": "足球门8x6", "country": "美国", "status": 1},
        ],
        db_path,
    )
    products = list_settings_products(db_path)["products"]
    for product in products:
        update_listing_scope(product["id"], "key", "足球门", db_path)
    first = next(item for item in products if item["msku"] == "GOAL-01")
    second = next(item for item in products if item["msku"] == "GOAL-02")
    upsert_daily_metric("2026-08-04", first["id"], "sales_amount", 300, "currency", "orders", db_path=db_path)
    upsert_daily_metric("2026-08-04", second["id"], "sales_amount", 700, "currency", "orders", db_path=db_path)

    target_path = tmp_path / "目标表.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "目标"
    sheet.append(HEADERS)
    sheet.append(["月", "2026-08", "足球门", 10, "", "GOAL-01", 1000, "", "", "", "", "", "", "单品目标"])
    workbook.save(target_path)
    import_targets(target_path, db_path)

    data = dashboard(db_path, date(2026, 8, 4))
    month = next(item for item in data["product_lines"][0]["windows"] if item["code"] == "month")
    target = next(item for item in month["targets"] if item["metric_code"] == "sales_amount")
    assert month["summary"]["sales_amount"] == 1000
    assert target["actual"] == 300
    assert target["target"] == 1000
    assert target["completion"] == 0.3
    assert "GOAL-01" in target["scope_note"]
