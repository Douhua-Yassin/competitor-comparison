from pathlib import Path

from app.main import (DEFAULT_INPUT, connection, import_workbook, init_db, normalize_size,
                      parse_amazon_html, parse_seller_sprite_html, save_record, table_data)


def test_existing_size_and_amazon_fixture_parser():
    assert normalize_size("13*13*9") == "13×13×9 ft"
    assert normalize_size("13FT X 13FT X 9FT") == "13×13×9 ft"
    data = parse_amazon_html(Path("tests/fixtures/product.html").read_text())
    assert data["crawl_status"] == "success" and data["price"] == 109.99
    assert data["rating_value"] == 3.9 and data["review_count"] == 416


def test_real_workbook_import():
    result = import_workbook(DEFAULT_INPUT)
    assert result["imported"] == 2
    with connection() as db:
        products = db.execute("select asin, brand, is_self from products").fetchall()
    assert {p["asin"] for p in products} == {"B0D3D2W989", "B0GCLSCTK2"}
    assert any(p["brand"] == "ORIENGEAR" and p["is_self"] for p in products)


def test_seller_sprite_fixture_prefers_detail_rank_and_parent_sales():
    sprite = parse_seller_sprite_html(Path("tests/fixtures/seller_sprite.html").read_text(encoding="utf-8"), "B0D3D2W989")
    assert sprite["seller_sprite_status"] == "loaded"
    assert sprite["asin"] == "B0D3D2W989" and sprite["brand"] == "ORIENGEAR"
    assert sprite["price"] == 109.99 and sprite["rating_value"] == 3.9 and sprite["review_count"] == 417
    assert sprite["parent_sales"] == "46" and sprite["size"] == "13FT"
    assert [r["text"] for r in sprite["rank_list"]] == ["#95,097 in Sports & Outdoors", "#10 in Baseball & Softball Batting Cages"]
    assert sprite["rank_text"] == "#10 in Baseball & Softball Batting Cages"


def test_sprite_na_sales_and_missing_root_are_not_fake_success():
    html = Path("tests/fixtures/seller_sprite.html").read_text(encoding="utf-8").replace(">46<", ">N/A<")
    assert parse_seller_sprite_html(html, "B0D3D2W989")["parent_sales"] is None
    assert parse_seller_sprite_html("<html></html>", "B0D3D2W989")["seller_sprite_status"] == "unavailable"


def test_delivery_fixture_uses_stable_selectors_only():
    html = Path("tests/fixtures/delivery_popup.html").read_text()
    assert "GLUXZipUpdateInput" in html and "GLUXZipUpdate input.a-button-input" not in html
    assert "GLUXConfirmClose" in html
    assert "a-popover-content-" not in html and "/html/" not in html


def test_partial_success_is_preserved_and_history_appends():
    init_db(); asin = "B0D3D2W989"
    before = connection().execute("select count(*) from crawl_records where asin=?", (asin,)).fetchone()[0]
    save_record({"asin": asin, "captured_at": "2026-07-28T12:00:00", "crawl_status": "partial_success", "price": 109.99,
                 "seller_sprite_status": "unavailable", "delivery_status": "delivery_already_set", "data_source": "amazon_public"}, "fixture")
    with connection() as db:
        after = db.execute("select count(*) from crawl_records where asin=?", (asin,)).fetchone()[0]
        row = db.execute("select crawl_status from crawl_records where asin=? order by id desc", (asin,)).fetchone()
    assert after == before + 1 and row["crawl_status"] == "partial_success"
    assert table_data("all")["products"]
