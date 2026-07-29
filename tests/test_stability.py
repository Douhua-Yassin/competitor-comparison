import asyncio
from pathlib import Path

from openpyxl import Workbook

import app.main as main


def make_book(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "打击笼"
    ws.append(["品牌", "尺寸", "ASIN", "星级（评价）", "售价", "是否我方"])
    ws.append(["OWN", "13", "B0D3D2W989", None, 100, "是"])
    wb.save(path)


def configure(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "data" / "monitor.db")
    monkeypatch.setattr(main, "INPUT_PATH", tmp_path / "产品输入表.xlsx")
    main.reset_sync_cache()
    main.init_db()


def test_merge_preserves_amazon_error_when_sprite_unavailable():
    merged = main.merge_sources(
        {"crawl_status": "blocked_or_captcha", "error_message": "Amazon CAPTCHA"},
        {"seller_sprite_status": "unavailable"},
    )
    assert merged["crawl_status"] == "blocked_or_captcha"
    assert merged["error_message"] == "Amazon CAPTCHA; seller_sprite_unavailable"


def test_unchanged_workbook_skips_full_read(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    make_book(main.INPUT_PATH)
    first = main.sync_workbook()
    monkeypatch.setattr(
        main,
        "_read_workbook",
        lambda _: (_ for _ in ()).throw(AssertionError("should not read")),
    )
    second = main.sync_workbook()
    assert second == first


def test_database_uses_wal_and_busy_timeout(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    with main.connection() as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert db.execute("PRAGMA busy_timeout").fetchone()[0] == 15000


def test_join_messages_removes_duplicates():
    assert main.join_messages(
        "Amazon CAPTCHA", "seller_sprite_unavailable", "Amazon CAPTCHA"
    ) == "Amazon CAPTCHA; seller_sprite_unavailable"


def test_connect_browser_uses_websocket_and_extended_timeout(monkeypatch):
    calls = []
    expected_browser = object()

    class FakeChromium:
        async def connect_over_cdp(self, endpoint, timeout):
            calls.append((endpoint, timeout))
            return expected_browser

    class FakePlaywright:
        chromium = FakeChromium()

    monkeypatch.setattr(
        main,
        "get_cdp_info",
        lambda: {
            "Browser": "Chrome/134.0.0.0",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/test",
        },
    )

    browser = asyncio.run(main.connect_browser(FakePlaywright()))
    assert browser is expected_browser
    assert calls == [
        (
            "ws://127.0.0.1:9222/devtools/browser/test",
            main.CDP_CONNECT_TIMEOUT_MS,
        )
    ]
    assert main.CDP_CONNECT_TIMEOUT_MS == 120_000
