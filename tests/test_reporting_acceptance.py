from __future__ import annotations

import json
from pathlib import Path

from app.reporting.dashboard_db import (
    create_sync_run,
    finish_sync_run,
    init_dashboard_db,
    list_settings_products,
    update_listing_scope,
    upsert_daily_metric,
    upsert_listings,
    upsert_stores,
)
from app.reporting.sync_acceptance import (
    build_sync_acceptance,
    write_acceptance_report,
)


def _seed_products(db_path: Path) -> list[int]:
    upsert_stores(
        [{"sid": 10, "name": "美国测试店", "country": "美国"}],
        db_path,
    )
    upsert_listings(
        [
            {
                "sid": 10,
                "asin": "B000GOAL01",
                "msku": "GOAL-01",
                "product_name": "足球门一号",
                "country": "美国",
            },
            {
                "sid": 10,
                "asin": "B000GOAL02",
                "msku": "GOAL-02",
                "product_name": "足球门二号",
                "country": "美国",
            },
            {
                "sid": 10,
                "asin": "B000OTHER1",
                "msku": "OTHER-01",
                "product_name": "非负责产品",
                "country": "美国",
            },
        ],
        db_path,
        fetched_sids=[10],
    )
    products = list_settings_products(db_path)["products"]
    selected: list[int] = []
    for product in products:
        if product["msku"] == "GOAL-01":
            update_listing_scope(product["id"], "key", "足球门", db_path)
            selected.append(product["id"])
        elif product["msku"] == "GOAL-02":
            update_listing_scope(product["id"], "normal", "足球门", db_path)
            selected.append(product["id"])
    return selected


def test_acceptance_without_sync_run_is_explicit(tmp_path: Path) -> None:
    database = tmp_path / "reporting.db"
    init_dashboard_db(database)

    result = build_sync_acceptance(database, generated_at="2026-08-06T05:00:00+00:00")

    assert result["state"] == "no_sync"
    assert result["latest_run"] is None
    assert result["catalog"]["active_listings"] == 0
    assert "尚无领星同步记录" in result["message"]


def test_acceptance_reports_endpoint_and_product_line_coverage(tmp_path: Path) -> None:
    database = tmp_path / "reporting.db"
    first, second = _seed_products(database)
    run_id = create_sync_run("2026-07-24", "2026-08-06", database)

    upsert_daily_metric(
        "2026-08-06",
        first,
        "sales_amount",
        100,
        "currency",
        "orders",
        db_path=database,
    )
    upsert_daily_metric(
        "2026-08-06",
        first,
        "units",
        2,
        "count",
        "orders",
        db_path=database,
    )
    for listing_id, value in ((first, 8), (second, 12)):
        upsert_daily_metric(
            "2026-08-06",
            listing_id,
            "fba_available",
            value,
            "count",
            "fba_inventory",
            db_path=database,
        )
    upsert_daily_metric(
        "2026-08-05",
        first,
        "ad_spend",
        20,
        "currency",
        "sp_product_report",
        db_path=database,
    )
    finish_sync_run(
        run_id,
        "partial_success",
        catalog_count=3,
        selected_count=2,
        metric_count=5,
        message="同步完成，但广告接口部分失败",
        details={
            "warnings": ["sp_product_report 同步失败：403 授权失效"],
            "finalized_count": 4,
        },
        db_path=database,
    )

    result = build_sync_acceptance(database, generated_at="2026-08-06T05:00:00+00:00")

    assert result["state"] == "ready"
    assert result["catalog"] == {
        "active_listings": 3,
        "selected_listings": 2,
        "key_listings": 1,
        "normal_listings": 1,
        "product_lines": 1,
        "stores": 1,
    }
    endpoint = {item["code"]: item for item in result["endpoints"]}
    assert endpoint["orders"]["status"] == "partial"
    assert endpoint["orders"]["listings_with_data"] == 1
    assert endpoint["after_sales"]["status"] == "empty"
    assert endpoint["fba_inventory"]["status"] == "covered"
    assert endpoint["fba_inventory"]["coverage_ratio"] == 1.0
    assert endpoint["sp_product_report"]["status"] == "warning"
    assert result["blocking_issues"] == ["sp_product_report 同步失败：403 授权失效"]

    product_line = result["product_lines"][0]
    assert product_line["product_line"] == "足球门"
    assert product_line["listing_count"] == 2
    assert product_line["endpoints"]["orders"]["listings_with_data"] == 1
    assert product_line["endpoints"]["fba_inventory"]["listings_with_data"] == 2


def test_acceptance_detects_scope_change_after_sync(tmp_path: Path) -> None:
    database = tmp_path / "reporting.db"
    selected = _seed_products(database)
    run_id = create_sync_run("2026-07-24", "2026-08-06", database)
    finish_sync_run(
        run_id,
        "success",
        catalog_count=3,
        selected_count=1,
        metric_count=0,
        message="同步完成",
        details={},
        db_path=database,
    )

    result = build_sync_acceptance(database)

    assert len(selected) == 2
    assert any("当前设置为 2 个" in item for item in result["blocking_issues"])


def test_acceptance_export_writes_markdown_and_json(tmp_path: Path) -> None:
    database = tmp_path / "reporting.db"
    _seed_products(database)
    run_id = create_sync_run("2026-07-24", "2026-08-06", database)
    finish_sync_run(
        run_id,
        "success",
        catalog_count=3,
        selected_count=2,
        metric_count=0,
        message="同步完成",
        details={"finalized_count": 0},
        db_path=database,
    )
    output = tmp_path / "acceptance"

    markdown_path = write_acceptance_report("md", database, output)
    json_path = write_acceptance_report("json", database, output)

    markdown = markdown_path.read_text(encoding="utf-8")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert "# 领星经营数据同步验收报告" in markdown
    assert "足球门" in markdown
    assert payload["latest_run"]["selected_count"] == 2
    assert markdown_path.parent.parent == output
    assert json_path.parent.parent == output


def test_acceptance_rejects_unknown_export_format(tmp_path: Path) -> None:
    database = tmp_path / "reporting.db"
    init_dashboard_db(database)

    try:
        write_acceptance_report("html", database, tmp_path)
    except ValueError as exc:
        assert "只支持 md 或 json" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("unknown format should fail")
