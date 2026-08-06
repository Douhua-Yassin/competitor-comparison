from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.main as main
from app.lingxing_audit.config import AuditConfigurationError, AuditSettings
from app.reporting import dashboard_routes, lingxing_sync, report_archive, targets
from app.reporting.dashboard_service import _aggregate
from app.reporting.report_generator import _safe_filename_component


def test_competitor_crawl_reserves_batch_before_background_task(monkeypatch):
    main.status.update(running=False, message="idle", total=0, current_asin=None)
    created: list[object] = []

    monkeypatch.setattr(main, "sync_or_raise", lambda: {})
    monkeypatch.setattr(main, "active_asins", lambda: ["B000TEST01"])
    monkeypatch.setattr(main, "check_cdp_available", lambda: True)

    def capture(coro):
        created.append(coro)
        return SimpleNamespace(done=lambda: False)

    monkeypatch.setattr(main.asyncio, "create_task", capture)

    async def exercise():
        first = await main.api_crawl()
        assert first == {"started": True, "total": 1}
        assert main.status["running"] is True
        with pytest.raises(HTTPException) as exc_info:
            await main.api_crawl()
        assert exc_info.value.status_code == 409

    try:
        asyncio.run(exercise())
    finally:
        for coro in created:
            coro.close()
        main.status["running"] = False


def test_competitor_crawl_task_creation_failure_releases_reservation(monkeypatch):
    main.status.update(running=False, message="idle", total=0, current_asin=None)
    monkeypatch.setattr(main, "sync_or_raise", lambda: {})
    monkeypatch.setattr(main, "active_asins", lambda: ["B000TEST01"])
    monkeypatch.setattr(main, "check_cdp_available", lambda: True)

    def fail(coro):
        coro.close()
        raise RuntimeError("cannot schedule")

    monkeypatch.setattr(main.asyncio, "create_task", fail)
    with pytest.raises(RuntimeError, match="cannot schedule"):
        asyncio.run(main.api_crawl())
    assert main.status["running"] is False
    assert main.status["message"] == "抓取任务启动失败"


def test_cdp_probe_uses_proxy_free_opener(monkeypatch):
    captured: dict[str, object] = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            return json.dumps(
                {
                    "Browser": "Chrome/134.0.0.0",
                    "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/test",
                }
            ).encode()

    class Opener:
        def open(self, url, timeout):
            captured["url"] = url
            captured["timeout"] = timeout
            return Response()

    def build_opener(handler):
        captured["proxies"] = handler.proxies
        return Opener()

    monkeypatch.setattr(main.urllib.request, "build_opener", build_opener)
    info = main.get_cdp_info("http://127.0.0.1:9222")
    assert info and info["Browser"].startswith("Chrome/")
    assert captured["proxies"] == {}
    assert captured["url"] == "http://127.0.0.1:9222/json/version"


def test_reporting_sync_start_reservation_is_atomic():
    lingxing_sync._SYNC_STATUS["running"] = False
    assert lingxing_sync.reserve_sync_start() is True
    assert lingxing_sync.reserve_sync_start() is False
    lingxing_sync.cancel_sync_reservation("cancelled")
    assert lingxing_sync.sync_status()["running"] is False


def test_reporting_task_creation_failure_releases_reservation(monkeypatch):
    lingxing_sync._SYNC_STATUS["running"] = False

    def fail(coro):
        coro.close()
        raise RuntimeError("cannot schedule")

    monkeypatch.setattr(dashboard_routes.asyncio, "create_task", fail)
    with pytest.raises(RuntimeError, match="cannot schedule"):
        asyncio.run(dashboard_routes.api_start_sync())
    assert lingxing_sync.sync_status()["running"] is False


def test_reporting_configuration_failure_clears_running_status(monkeypatch):
    lingxing_sync._SYNC_STATUS["running"] = False

    class BrokenSettings:
        @staticmethod
        def load():
            raise RuntimeError("bad configuration")

    monkeypatch.setattr(lingxing_sync, "AuditSettings", BrokenSettings)
    with pytest.raises(RuntimeError, match="bad configuration"):
        asyncio.run(lingxing_sync.run_recent_sync())
    state = lingxing_sync.sync_status()
    assert state["running"] is False
    assert "bad configuration" in state["message"]


def test_sync_status_returns_independent_warning_list():
    lingxing_sync._SYNC_STATUS["warnings"] = ["original"]
    copy = lingxing_sync.sync_status()
    copy["warnings"].append("mutated")
    assert lingxing_sync._SYNC_STATUS["warnings"] == ["original"]


def test_dashboard_ratios_are_derived_from_additive_totals():
    rows = []
    values = {
        1: {"impressions": 100, "clicks": 10, "ad_spend": 20, "ad_sales": 100, "ad_orders": 2},
        2: {"impressions": 900, "clicks": 45, "ad_spend": 90, "ad_sales": 600, "ad_orders": 18},
    }
    for listing_id, metrics in values.items():
        for code, value in metrics.items():
            rows.append(
                {
                    "metric_date": "2026-08-04",
                    "listing_id": listing_id,
                    "metric_code": code,
                    "metric_value": value,
                }
            )
        # Deliberately misleading source ratios. The aggregate must not average them.
        rows.extend(
            [
                {"metric_date": "2026-08-04", "listing_id": listing_id, "metric_code": "ctr", "metric_value": 0.9},
                {"metric_date": "2026-08-04", "listing_id": listing_id, "metric_code": "cpc", "metric_value": 99},
            ]
        )

    summary = _aggregate(rows)
    assert summary["ctr"] == pytest.approx(55 / 1000)
    assert summary["cpc"] == pytest.approx(110 / 55)
    assert summary["cvr"] == pytest.approx(20 / 55)
    assert summary["acos"] == pytest.approx(110 / 700)
    assert summary["roas"] == pytest.approx(700 / 110)


def test_dashboard_inventory_sums_latest_value_for_each_listing():
    summary = _aggregate(
        [
            {"metric_date": "2026-08-03", "listing_id": 1, "metric_code": "fba_available", "metric_value": 10},
            {"metric_date": "2026-08-04", "listing_id": 1, "metric_code": "fba_available", "metric_value": 8},
            {"metric_date": "2026-08-02", "listing_id": 2, "metric_code": "fba_available", "metric_value": 20},
        ]
    )
    assert summary["fba_available"] == 28


def test_target_number_rejects_nan_and_infinity():
    with pytest.raises(ValueError, match="有限数字"):
        targets._number("nan")
    with pytest.raises(ValueError, match="有限数字"):
        targets._number("inf")


def test_target_import_closes_workbook(tmp_path: Path, monkeypatch):
    source = tmp_path / "目标表.xlsx"
    source.write_bytes(b"placeholder")
    closed = {"value": False}

    class FakeSheet:
        def iter_rows(self, values_only=True):
            assert values_only is True
            return iter(
                [
                    ("周期类型", "周期", "产品线", "销售额目标"),
                    ("日", "2026-08-06", "足球门", 100),
                ]
            )

    class FakeWorkbook:
        sheetnames = ["目标"]
        active = FakeSheet()

        def __getitem__(self, name):
            assert name == "目标"
            return self.active

        def close(self):
            closed["value"] = True

    monkeypatch.setattr(targets, "load_workbook", lambda *args, **kwargs: FakeWorkbook())
    result = targets.import_targets(source, tmp_path / "reporting.db")
    assert result["imported"] is True
    assert closed["value"] is True


def test_report_archive_rejects_tampered_file(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(report_archive, "ROOT", tmp_path)
    artifact = tmp_path / "data" / "reports" / "2026-08-06" / "report.docx"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"original")
    database = tmp_path / "reporting.db"
    archived = report_archive.archive_report(
        product_line="足球门",
        report_type="day",
        period_start="2026-08-06",
        period_end="2026-08-06",
        analysis_source="rules",
        analysis_warning=None,
        data_snapshot={},
        target_snapshot=[],
        note_snapshot={},
        analysis={},
        artifact_path=artifact,
        db_path=database,
    )
    assert report_archive.resolve_report_artifact(archived["id"], database) == artifact.resolve()
    artifact.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="校验失败"):
        report_archive.resolve_report_artifact(archived["id"], database)


def test_report_filename_component_is_windows_safe_and_bounded():
    value = "足球门" * 100 + '/:*?"<>|'
    result = _safe_filename_component(value)
    assert len(result) <= 80
    assert not any(char in result for char in '\\/:*?"<>|')
    assert result == _safe_filename_component(value)
    assert result != _safe_filename_component(value + "另一条产品线")


def test_lingxing_base_url_rejects_embedded_credentials_and_query(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text(
        "LINGXING_APP_ID=test-id\n"
        "LINGXING_APP_SECRET=test-secret\n"
        "LINGXING_BASE_URL=https://user:password@openapi.lingxing.com?token=secret\n",
        encoding="utf-8",
    )
    with pytest.raises(AuditConfigurationError, match="不得包含"):
        AuditSettings.load(env)


def test_database_context_managers_close_connections(tmp_path: Path, monkeypatch):
    import sqlite3
    from app.reporting.dashboard_db import connection as reporting_connection

    monkeypatch.setattr(main, "DATA_DIR", tmp_path / "monitor-data")
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "monitor-data" / "monitor.db")
    with main.connection() as monitor_db:
        monitor_db.execute("CREATE TABLE sample (id INTEGER)")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        monitor_db.execute("SELECT 1")

    with reporting_connection(tmp_path / "reporting.db") as reporting_db:
        reporting_db.execute("CREATE TABLE sample (id INTEGER)")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        reporting_db.execute("SELECT 1")


def test_zero_sales_is_not_replaced_by_listing_rollup(tmp_path: Path):
    from app.reporting.dashboard_service import _window_payload_for_range

    payload = _window_payload_for_range(
        code="day",
        label="当日",
        start=__import__("datetime").date(2026, 8, 6),
        end=__import__("datetime").date(2026, 8, 6),
        metrics=[
            {
                "metric_date": "2026-08-06",
                "listing_id": 1,
                "metric_code": "sales_amount",
                "metric_value": 0,
            }
        ],
        products=[{"id": 1, "product_line": "足球门"}],
        snapshots={1: {"sales_amt_1d": 999, "sales_qty_1d": 9}},
        note={"content": "", "updated_at": None},
        period_key="2026-08-06:2026-08-06",
        db_path=tmp_path / "reporting.db",
        target_period_type=None,
        fallback_code="day",
    )
    assert payload["summary"]["sales_amount"] == 0
    assert payload["source_note"] is None


def test_month_dashboard_loads_previous_equal_length_period(tmp_path: Path):
    from datetime import date
    from app.reporting.dashboard_db import (
        list_settings_products,
        update_listing_scope,
        upsert_daily_metric,
        upsert_listings,
        upsert_stores,
    )
    from app.reporting.dashboard_service import dashboard

    db_path = tmp_path / "reporting.db"
    upsert_stores([{"sid": 10, "name": "美国店", "country": "美国"}], db_path)
    upsert_listings(
        [{"sid": 10, "asin": "B000TEST01", "msku": "GOAL-01", "product_name": "足球门"}],
        db_path,
    )
    product = list_settings_products(db_path)["products"][0]
    update_listing_scope(product["id"], "key", "足球门", db_path)
    upsert_daily_metric("2026-07-01", product["id"], "sales_amount", 100, "currency", "orders", db_path=db_path)
    upsert_daily_metric("2026-08-01", product["id"], "sales_amount", 200, "currency", "orders", db_path=db_path)

    data = dashboard(db_path, date(2026, 8, 31))
    month = next(
        window
        for window in data["product_lines"][0]["windows"]
        if window["code"] == "month"
    )
    assert month["comparisons"]["sales_amount"] == pytest.approx(1.0)


def test_seller_sprite_parser_never_uses_another_asin_panel():
    html = '''
    <div name="seller-sprite-extension-quick-view-B000OTHER1">
      <span class="word-title">价格：</span><span>$99.99</span>
    </div>
    '''
    result = main.parse_seller_sprite_html(html, "B000TARGET1")
    assert result == {"seller_sprite_status": "unavailable"}
