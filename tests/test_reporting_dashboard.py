from __future__ import annotations

from datetime import date
from pathlib import Path

from app.reporting.dashboard_db import (
    connection,
    finalize_before,
    init_dashboard_db,
    list_settings_products,
    save_note,
    update_listing_scope,
    upsert_daily_metric,
    upsert_listings,
    upsert_stores,
)
from app.reporting.dashboard_service import dashboard, period_keys
from app.reporting.lingxing_sync import _build_listing_index, _persist_payload


def seed_listing(db_path: Path, level: str = "key", product_line: str = "足球门") -> int:
    init_dashboard_db(db_path)
    upsert_stores([{"sid": 10, "name": "美国店", "country": "美国"}], db_path)
    upsert_listings(
        [
            {
                "sid": 10,
                "asin": "B000TEST01",
                "msku": "GOAL-01",
                "lsku": "L-GOAL-01",
                "product_name": "足球门 6x4",
                "country": "美国",
                "currency_code": "USD",
                "status": 1,
                "deleted": 0,
            }
        ],
        db_path,
    )
    product = list_settings_products(db_path)["products"][0]
    update_listing_scope(product["id"], level, product_line, db_path)
    return int(product["id"])


def test_settings_are_lingxing_based_and_two_buttons_map_to_three_states(tmp_path: Path):
    db_path = tmp_path / "reporting.db"
    listing_id = seed_listing(db_path)
    data = list_settings_products(db_path)
    assert data["countries"] == ["美国"]
    assert data["products"][0]["store_name"] == "美国店"
    assert data["products"][0]["responsibility_level"] == "key"

    updated = update_listing_scope(listing_id, "normal", "足球门", db_path)
    assert updated["responsibility_level"] == "normal"
    cancelled = update_listing_scope(listing_id, "not_mine", "足球门", db_path)
    assert cancelled["responsibility_level"] == "not_mine"
    assert cancelled["product_line"] is None


def test_recent_window_can_update_but_final_history_cannot_be_overwritten(tmp_path: Path):
    db_path = tmp_path / "reporting.db"
    listing_id = seed_listing(db_path)
    upsert_daily_metric(
        "2026-07-01", listing_id, "sales_amount", 100, "currency", "orders", db_path=db_path
    )
    assert finalize_before("2026-07-23", db_path) == 1
    upsert_daily_metric(
        "2026-07-01", listing_id, "sales_amount", 999, "currency", "orders", db_path=db_path
    )
    with connection(db_path) as db:
        row = db.execute(
            "SELECT metric_value, is_final FROM lx_daily_metrics WHERE listing_id=?",
            (listing_id,),
        ).fetchone()
    assert row["metric_value"] == 100
    assert row["is_final"] == 1


def test_payload_persistence_keeps_only_selected_listing_and_aggregates(
    tmp_path: Path, monkeypatch
):
    db_path = tmp_path / "reporting.db"
    listing_id = seed_listing(db_path)
    rows = [
        {
            "id": listing_id,
            "sid": 10,
            "asin": "B000TEST01",
            "msku": "GOAL-01",
            "lsku": "L-GOAL-01",
        }
    ]
    index = _build_listing_index(rows)
    payload = {
        "data": [
            {
                "sid": 10,
                "asin": "B000TEST01",
                "order_date": "2026-08-04",
                "quantity": 2,
                "sales_amount": 50,
            },
            {
                "sid": 10,
                "asin": "B000TEST01",
                "order_date": "2026-08-04",
                "quantity": 1,
                "sales_amount": 25,
            },
            {
                "sid": 10,
                "asin": "B000OTHER1",
                "order_date": "2026-08-04",
                "quantity": 99,
                "sales_amount": 999,
            },
        ]
    }
    from app.reporting import lingxing_sync

    original = lingxing_sync.upsert_daily_metric

    def write_to_tmp(*args, **kwargs):
        kwargs["db_path"] = db_path
        return original(*args, **kwargs)

    monkeypatch.setattr(lingxing_sync, "upsert_daily_metric", write_to_tmp)
    assert (
        _persist_payload(
            "orders", payload, index, date(2026, 7, 22), date(2026, 8, 4)
        )
        == 2
    )

    with connection(db_path) as db:
        metrics = {
            row["metric_code"]: row["metric_value"]
            for row in db.execute(
                "SELECT metric_code, metric_value FROM lx_daily_metrics"
            )
        }
    assert metrics == {"sales_amount": 75, "units": 3}


def test_dashboard_only_shows_key_lines_and_loads_period_notes(tmp_path: Path):
    db_path = tmp_path / "reporting.db"
    key_id = seed_listing(db_path, "key", "足球门")
    upsert_daily_metric(
        "2026-08-04", key_id, "sales_amount", 300, "currency", "orders", db_path=db_path
    )
    upsert_daily_metric(
        "2026-08-04",
        key_id,
        "ad_spend",
        30,
        "currency",
        "sp_product_report",
        db_path=db_path,
    )
    keys = period_keys(date(2026, 8, 4))
    save_note("足球门", "day", keys["day"], "今天降低了主推款广告预算。", db_path)

    normal_id = seed_second_listing(db_path)
    upsert_daily_metric(
        "2026-08-04", normal_id, "sales_amount", 500, "currency", "orders", db_path=db_path
    )

    data = dashboard(db_path, date(2026, 8, 4))
    assert [line["product_line"] for line in data["product_lines"]] == ["足球门"]
    day = next(
        item for item in data["product_lines"][0]["windows"] if item["code"] == "day"
    )
    assert day["summary"]["sales_amount"] == 300
    assert day["summary"]["tacos"] == 0.1
    assert "降低了" in day["note"]["content"]


def seed_second_listing(db_path: Path) -> int:
    upsert_listings(
        [
            {
                "sid": 10,
                "asin": "B000TEST01",
                "msku": "GOAL-01",
                "product_name": "足球门 6x4",
                "country": "美国",
                "status": 1,
            },
            {
                "sid": 10,
                "asin": "B000TEST02",
                "msku": "BOARD-01",
                "product_name": "普通黑板",
                "country": "美国",
                "status": 1,
            },
        ],
        db_path,
    )
    product = next(
        item
        for item in list_settings_products(db_path)["products"]
        if item["msku"] == "BOARD-01"
    )
    update_listing_scope(product["id"], "normal", "挂式黑板", db_path)
    return int(product["id"])
