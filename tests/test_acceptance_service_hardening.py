from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.reporting import dashboard_routes
from app.reporting.acceptance_service import (
    build_sync_acceptance,
    write_acceptance_report,
)
from app.reporting.dashboard_db import (
    connection,
    create_sync_run,
    finish_sync_run,
    init_dashboard_db,
    list_settings_products,
    update_listing_scope,
    upsert_listings,
    upsert_stores,
)
from app.reporting.dashboard_models import ListingScopeUpdate


def _seed_selected_listing(db_path: Path, product_line: str = "足球门") -> int:
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
            }
        ],
        db_path,
        fetched_sids=[10],
    )
    product = list_settings_products(db_path)["products"][0]
    update_listing_scope(product["id"], "key", product_line, db_path)
    return int(product["id"])


def test_running_sync_never_reports_partial_data_as_ready(tmp_path: Path) -> None:
    database = tmp_path / "reporting.db"
    _seed_selected_listing(database)
    create_sync_run("2026-07-24", "2026-08-06", database)

    result = build_sync_acceptance(
        database,
        generated_at="2026-08-06T06:00:00+00:00",
        runtime_running=True,
    )

    assert result["state"] == "syncing"
    assert result["endpoints"] == []
    assert result["product_lines"] == []
    assert "同步仍在运行" in result["message"]


def test_stale_running_record_is_reported_as_interrupted(tmp_path: Path) -> None:
    database = tmp_path / "reporting.db"
    _seed_selected_listing(database)
    create_sync_run("2026-07-24", "2026-08-06", database)

    result = build_sync_acceptance(database, runtime_running=False)

    assert result["state"] == "interrupted"
    assert result["endpoints"] == []
    assert any("当前没有同步任务" in item for item in result["blocking_issues"])


def test_acceptance_redacts_all_supported_credential_forms(tmp_path: Path) -> None:
    database = tmp_path / "reporting.db"
    _seed_selected_listing(database)
    run_id = create_sync_run("2026-07-24", "2026-08-06", database)
    finish_sync_run(
        run_id,
        "failed",
        catalog_count=1,
        selected_count=1,
        metric_count=0,
        message=(
            "Authorization: Bearer bearer-secret app_id=app-secret "
            "refresh_token=refresh-secret client_secret=client-secret"
        ),
        details={
            "warnings": [
                "https://example.test/path?api_key=query-secret&token=url-token"
            ]
        },
        db_path=database,
    )

    result = build_sync_acceptance(database)
    serialized = json.dumps(result, ensure_ascii=False)

    for secret in (
        "bearer-secret",
        "app-secret",
        "refresh-secret",
        "client-secret",
        "query-secret",
        "url-token",
    ):
        assert secret not in serialized
    assert "***redacted***" in serialized


def test_scope_change_is_detected_even_when_product_count_is_unchanged(
    tmp_path: Path,
) -> None:
    database = tmp_path / "reporting.db"
    listing_id = _seed_selected_listing(database)
    run_id = create_sync_run("2026-07-24", "2026-08-06", database)
    finish_sync_run(
        run_id,
        "success",
        catalog_count=1,
        selected_count=1,
        metric_count=0,
        message="同步完成",
        details={},
        db_path=database,
    )
    with connection(database) as db:
        db.execute(
            "UPDATE lx_sync_runs SET finished_at=? WHERE id=?",
            ("2026-08-06T06:00:00", run_id),
        )
        db.execute(
            "UPDATE lx_listings SET product_line=?, updated_at=? WHERE id=?",
            ("足球门新版", "2026-08-06T06:00:01+00:00", listing_id),
        )

    result = build_sync_acceptance(database)

    assert result["catalog"]["selected_listings"] == 1
    assert any("足球门新版 / GOAL-01" in item for item in result["blocking_issues"])


def test_rate_limit_and_timeout_warnings_are_blocking(tmp_path: Path) -> None:
    database = tmp_path / "reporting.db"
    _seed_selected_listing(database)
    run_id = create_sync_run("2026-07-24", "2026-08-06", database)
    finish_sync_run(
        run_id,
        "partial_success",
        catalog_count=1,
        selected_count=1,
        metric_count=0,
        message="同步完成但有告警",
        details={
            "warnings": [
                "sp_product_report 同步失败：429 rate limit",
                "orders 同步失败：network timeout",
            ]
        },
        db_path=database,
    )

    result = build_sync_acceptance(database)

    assert any("429 rate limit" in item for item in result["blocking_issues"])
    assert any("network timeout" in item for item in result["blocking_issues"])


def test_acceptance_export_is_atomic_and_cleans_failed_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "reporting.db"
    init_dashboard_db(database)
    output = tmp_path / "acceptance"

    def fail_write_text(self: Path, *args, **kwargs):  # noqa: ANN002, ANN003
        raise OSError("simulated disk failure")

    monkeypatch.setattr(Path, "write_text", fail_write_text)

    with pytest.raises(OSError, match="simulated disk failure"):
        write_acceptance_report("json", database, output)

    assert output.exists()
    assert list(output.iterdir()) == []


def test_markdown_export_escapes_dynamic_markdown_characters(tmp_path: Path) -> None:
    database = tmp_path / "reporting.db"
    _seed_selected_listing(database, "足球|门`重点`")
    run_id = create_sync_run("2026-07-24", "2026-08-06", database)
    finish_sync_run(
        run_id,
        "success",
        catalog_count=1,
        selected_count=1,
        metric_count=0,
        message="同步完成",
        details={},
        db_path=database,
    )

    report = write_acceptance_report("md", database, tmp_path / "acceptance")
    markdown = report.read_text(encoding="utf-8")

    assert "### 足球\\|门\\`重点\\`" in markdown


def test_scope_update_is_rejected_while_sync_is_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        dashboard_routes,
        "sync_status",
        lambda: {"running": True},
    )
    payload = ListingScopeUpdate(
        listing_id=1,
        responsibility_level="key",
        product_line="足球门",
    )

    with pytest.raises(HTTPException) as exc_info:
        dashboard_routes.api_update_product_scope(payload)

    assert exc_info.value.status_code == 409
    assert "同步期间不能修改" in str(exc_info.value.detail)
