from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

Document = pytest.importorskip("docx").Document

from app.reporting.dashboard_db import (
    list_settings_products,
    save_note,
    update_listing_scope,
    upsert_daily_metric,
    upsert_listings,
    upsert_stores,
)
from app.reporting.report_generator import generate_report


def test_rule_based_word_report_is_valid(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "reporting.db"
    upsert_stores([{"sid": 10, "name": "美国店", "country": "美国"}], db_path)
    upsert_listings(
        [
            {
                "sid": 10,
                "asin": "B000TEST01",
                "msku": "GOAL-01",
                "product_name": "足球门 6x4",
                "country": "美国",
                "status": 1,
            }
        ],
        db_path,
    )
    product = list_settings_products(db_path)["products"][0]
    update_listing_scope(product["id"], "key", "足球门", db_path)
    upsert_daily_metric(
        "2026-08-04",
        product["id"],
        "sales_amount",
        300,
        "currency",
        "orders",
        db_path=db_path,
    )
    upsert_daily_metric(
        "2026-08-04",
        product["id"],
        "ad_spend",
        30,
        "currency",
        "sp_product_report",
        db_path=db_path,
    )
    save_note(
        "足球门",
        "day",
        "2026-08-04:2026-08-04",
        "今天降低了广告预算。",
        db_path,
    )

    from app.reporting import report_generator

    original_dashboard = report_generator.dashboard

    def dashboard_for_test(*args, **kwargs):
        from app.reporting.dashboard_service import dashboard

        return dashboard(db_path, kwargs.get("today"))

    monkeypatch.setattr(report_generator, "dashboard", dashboard_for_test)
    monkeypatch.setattr(
        report_generator,
        "_deepseek_settings",
        lambda: {"api_key": "", "base_url": "", "model": ""},
    )
    try:
        path = generate_report(
            "足球门",
            "day",
            output_dir=tmp_path / "reports",
            today=date(2026, 8, 4),
        )
    finally:
        monkeypatch.setattr(report_generator, "dashboard", original_dashboard)

    assert path.exists()
    document = Document(path)
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "足球门经营日报" in text
    assert "今天降低了广告预算" in text
    assert len(document.tables) >= 2
