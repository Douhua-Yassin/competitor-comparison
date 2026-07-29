import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException
from openpyxl import Workbook

import app.main as main


def make_workbook(path: Path, sheets: list[tuple[str, list[list[object]]]]) -> None:
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets:
        ws = wb.create_sheet(name)
        ws.append(["品牌", "尺寸", "ASIN", "星级（评价）", "售价", "是否我方"])
        for row in rows:
            ws.append(row)
    wb.save(path)


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "data" / "monitor.db")
    monkeypatch.setattr(main, "INPUT_PATH", tmp_path / "产品输入表.xlsx")
    main.status.update(
        running=False,
        message="idle",
        success=0,
        failed=0,
        total=0,
        current_asin=None,
        browser_status="unknown",
        seller_sprite_status="unknown",
        delivery_status="unknown",
        last_sync=None,
        sync_error=None,
    )
    main.init_db()
    return tmp_path


def test_size_and_amazon_parser_select_last_rank():
    assert main.normalize_size("13*13*9") == "13×13×9 ft"
    assert main.normalize_size("13FT X 13FT X 9FT") == "13×13×9 ft"
    data = main.parse_amazon_html(Path("tests/fixtures/product.html").read_text())
    assert data["price"] == 109.99
    assert data["rating_value"] == 3.9
    assert data["review_count"] == 416
    assert data["rank_text"].startswith("#10 in Baseball")


def test_seller_sprite_real_shape():
    sprite = main.parse_seller_sprite_html(
        Path("tests/fixtures/seller_sprite.html").read_text(encoding="utf-8"),
        "B0D3D2W989",
    )
    assert sprite["seller_sprite_status"] == "loaded"
    assert sprite["price"] == 109.99
    assert sprite["rating_value"] == 3.9
    assert sprite["review_count"] == 417
    assert sprite["parent_sales"] == "46"
    assert sprite["rank_text"] == "#7 in Baseball & Softball Batting Cages"


def test_seller_sprite_overrides_missing_amazon_price():
    amazon = {
        "crawl_status": "failed",
        "price": None,
        "price_text": None,
        "sales_text": None,
        "rank_text": None,
        "rating_value": None,
        "review_count": None,
        "error_message": "no public price",
    }
    sprite = main.parse_seller_sprite_html(
        Path("tests/fixtures/seller_sprite.html").read_text(encoding="utf-8"),
        "B0D3D2W989",
    )
    merged = main.merge_sources(amazon, sprite)
    assert merged["crawl_status"] == "success"
    assert merged["data_source"] == "seller_sprite"
    assert merged["price"] == 109.99
    assert merged["sales_text"] == "46"


def test_sync_multiple_sheets_and_cross_sheet_asin(isolated):
    make_workbook(
        main.INPUT_PATH,
        [
            ("打击笼", [["ORIENGEAR", "13*13*9", "B0D3D2W989", "3.9(417)", 109.99, "是"]]),
            (
                "足球门",
                [
                    ["VANTEX", "12 x 6", "B0D3D2W989", "4.0(20)", 129.99, "否"],
                    ["FORZA", "12×6", "B0GCLSCTK2", "4.5(100)", 139.99, "否"],
                ],
            ),
            ("空表", []),
        ],
    )
    result = main.sync_workbook()
    assert result == {
        "product_lines": 2,
        "items": 3,
        "unique_asins": 2,
        "synced_at": result["synced_at"],
    }
    with main.connection() as db:
        lines = db.execute(
            "SELECT name FROM product_lines WHERE active=1 ORDER BY sheet_order"
        ).fetchall()
        products = db.execute("SELECT asin FROM products WHERE enabled=1").fetchall()
        configs = db.execute(
            """
            SELECT pl.name, pli.brand, pli.size_normalized, pli.is_self
            FROM product_line_items pli JOIN product_lines pl ON pl.id=pli.product_line_id
            WHERE pli.asin='B0D3D2W989' AND pli.active=1 ORDER BY pl.sheet_order
            """
        ).fetchall()
    assert [row[0] for row in lines] == ["打击笼", "足球门"]
    assert {row[0] for row in products} == {"B0D3D2W989", "B0GCLSCTK2"}
    assert [tuple(row) for row in configs] == [
        ("打击笼", "ORIENGEAR", "13×13×9 ft", 1),
        ("足球门", "VANTEX", "12×6 ft", 0),
    ]


def test_sheet_and_item_removal_preserves_history(isolated):
    make_workbook(
        main.INPUT_PATH,
        [
            ("打击笼", [["A", "13*13*9", "B0D3D2W989", None, 109.99, "是"]]),
            ("足球门", [["B", "12*6", "B0GCLSCTK2", None, 129.99, "否"]]),
        ],
    )
    main.sync_workbook()
    main.save_record(
        {
            "asin": "B0GCLSCTK2",
            "captured_at": "2026-07-28T12:00:00",
            "crawl_status": "success",
            "price": 129.99,
        },
        "fixture",
    )
    make_workbook(
        main.INPUT_PATH,
        [("打击笼", [["A", "13*13*9", "B0D3D2W989", None, 109.99, "是"]])],
    )
    main.sync_workbook()
    with main.connection() as db:
        assert db.execute("SELECT enabled FROM products WHERE asin='B0GCLSCTK2'").fetchone()[0] == 0
        assert db.execute("SELECT active FROM product_lines WHERE name='足球门'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM crawl_records WHERE asin='B0GCLSCTK2'").fetchone()[0] == 1


def test_table_is_scoped_to_selected_line_and_price_baseline(isolated):
    make_workbook(
        main.INPUT_PATH,
        [
            (
                "打击笼",
                [
                    ["OWN", "13*13*9", "B0D3D2W989", None, None, "是"],
                    ["COMP", "13×13×9", "B0GCLSCTK2", None, None, "否"],
                ],
            ),
            (
                "足球门",
                [["OTHER", "13×13×9", "B0ABCDEFGH", None, None, "是"]],
            ),
        ],
    )
    main.sync_workbook()
    for asin, price in [
        ("B0D3D2W989", 100.0),
        ("B0GCLSCTK2", 90.0),
        ("B0ABCDEFGH", 50.0),
    ]:
        main.save_record(
            {
                "asin": asin,
                "captured_at": "2026-07-28T12:00:00",
                "crawl_status": "success",
                "price": price,
                "price_text": f"${price}",
            },
            "fixture",
        )
    with main.connection() as db:
        line_id = db.execute("SELECT id FROM product_lines WHERE name='打击笼'").fetchone()[0]
    data = main.table_data("all", line_id)
    assert [product["asin"] for product in data["products"]] == ["B0D3D2W989", "B0GCLSCTK2"]
    competitor = next(product for product in data["products"] if product["asin"] == "B0GCLSCTK2")
    assert competitor["cells"][0]["tone"] == "low"


def test_day_uses_latest_success_before_later_failure(isolated):
    make_workbook(
        main.INPUT_PATH,
        [("打击笼", [["OWN", "13", "B0D3D2W989", None, None, "是"]])],
    )
    main.sync_workbook()
    main.save_record(
        {"asin": "B0D3D2W989", "captured_at": "2026-07-28T10:00:00", "crawl_status": "success", "price": 100.0},
        "fixture",
    )
    main.save_record(
        {"asin": "B0D3D2W989", "captured_at": "2026-07-28T12:00:00", "crawl_status": "failed", "error_message": "later failure"},
        "fixture",
    )
    data = main.table_data("all")
    assert data["products"][0]["cells"][0]["record"]["price"] == 100.0


def test_cdp_unavailable_blocks_batch_without_failure_records(isolated, monkeypatch):
    make_workbook(
        main.INPUT_PATH,
        [("打击笼", [["OWN", "13", "B0D3D2W989", None, None, "是"]])],
    )
    monkeypatch.setattr(main, "check_cdp_available", lambda: False)
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(main.api_crawl())
    assert exc_info.value.status_code == 503
    with main.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM crawl_records").fetchone()[0] == 0
    assert main.status["message"] == "请先启动插件浏览器"


def test_sheet_rename_replaces_visible_tab_and_keeps_history(isolated):
    make_workbook(
        main.INPUT_PATH,
        [("旧名称", [["OWN", "13", "B0D3D2W989", None, None, "是"]])],
    )
    main.sync_workbook()
    main.save_record(
        {"asin": "B0D3D2W989", "captured_at": "2026-07-28T12:00:00", "crawl_status": "success", "price": 100.0},
        "fixture",
    )
    make_workbook(
        main.INPUT_PATH,
        [("新名称", [["OWN", "13", "B0D3D2W989", None, None, "是"]])],
    )
    main.sync_workbook()
    data = main.table_data("all")
    assert [line["name"] for line in data["product_lines"]] == ["新名称"]
    with main.connection() as db:
        assert db.execute("SELECT active FROM product_lines WHERE name='旧名称'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM crawl_records WHERE asin='B0D3D2W989'").fetchone()[0] == 1


def test_empty_sheet_is_hidden(isolated):
    make_workbook(main.INPUT_PATH, [("空白产品线", [])])
    main.sync_workbook()
    assert main.table_data("all")["product_lines"] == []


def test_missing_workbook_is_explicit(isolated):
    with pytest.raises(main.WorkbookSyncError, match="未找到产品输入表"):
        main.sync_workbook()
