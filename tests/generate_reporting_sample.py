from __future__ import annotations

import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from openpyxl import Workbook

from app.reporting import analysis_engine
from app.reporting.dashboard_db import (
    list_settings_products,
    save_note,
    update_listing_scope,
    upsert_daily_metric,
    upsert_listings,
    upsert_stores,
)
from app.reporting.report_generator import generate_report
from app.reporting.targets import import_targets


def main() -> None:
    root = PROJECT_ROOT / "artifacts" / "reporting-sample"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    db_path = root / "reporting.db"

    upsert_stores([{"sid": 10, "name": "美国示例店", "country": "美国"}], db_path)
    upsert_listings(
        [
            {
                "sid": 10,
                "asin": f"B000SAMPLE{index}",
                "msku": f"GOAL-{index:02d}",
                "product_name": f"足球门 {size}",
                "country": "美国",
                "status": 1,
            }
            for index, size in enumerate(("6x4", "8x6", "10x6.5"), start=1)
        ],
        db_path,
    )
    products = list_settings_products(db_path)["products"]
    for product in products:
        update_listing_scope(product["id"], "key", "足球门", db_path)

    current = date(2026, 8, 20)
    for offset in range(20):
        metric_date = date(2026, 8, 1) + timedelta(days=offset)
        for product_index, product in enumerate(products, start=1):
            sales = 430 + offset * 18 + product_index * 75
            units = 5 + (offset % 4) + product_index
            spend = 48 + offset * 1.4 + product_index * 7
            stock = 260 - offset * 3 - product_index * 12
            upsert_daily_metric(metric_date.isoformat(), product["id"], "sales_amount", sales, "currency", "orders", db_path=db_path)
            upsert_daily_metric(metric_date.isoformat(), product["id"], "units", units, "count", "orders", db_path=db_path)
            upsert_daily_metric(metric_date.isoformat(), product["id"], "ad_spend", spend, "currency", "sp_product_report", db_path=db_path)
            upsert_daily_metric(metric_date.isoformat(), product["id"], "ad_sales", sales * 0.42, "currency", "sp_product_report", db_path=db_path)
            upsert_daily_metric(metric_date.isoformat(), product["id"], "fba_available", stock, "count", "fba_inventory", db_path=db_path)

    save_note(
        "足球门",
        "month",
        "2026-08",
        "本月完成了主推款广告结构调整。6x4承担流量，8x6和10x6.5控制广告并承担利润。\n"
        "目前主要风险是主推款库存下降较快，需要采购确认九月补货时间。\n"
        "下阶段计划：继续观察TACOS和自然单占比，并申请补货优先级支持。",
        db_path,
    )

    target_path = root / "目标表.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "目标"
    sheet.append([
        "周期类型", "周期", "产品线", "店铺SID", "ASIN", "MSKU",
        "销售额目标", "销量目标", "利润目标", "利润率目标",
        "TACOS目标", "广告花费目标", "FBA可售库存目标", "备注",
    ])
    sheet.append(["月", "2026-08", "足球门", "", "", "", 45000, 600, 8000, "16%", "12%", 6000, 420, "八月经营目标"])
    workbook.save(target_path)
    import_targets(target_path, db_path)

    original_settings = analysis_engine.deepseek_settings
    analysis_engine.deepseek_settings = lambda _root: {
        "api_key": "",
        "base_url": "",
        "model": "",
        "timeout": 90,
        "max_tokens": 4096,
    }
    try:
        output = generate_report(
            "足球门",
            "month",
            output_dir=root,
            today=current,
            db_path=db_path,
        )
    finally:
        analysis_engine.deepseek_settings = original_settings
    if not output.exists():
        raise RuntimeError("sample report was not created")
    print("REPORT_SAMPLE_CREATED")


if __name__ == "__main__":
    main()
