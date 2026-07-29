from pathlib import Path

main_path = Path("app/main.py")
text = main_path.read_text(encoding="utf-8")

if "CDP_CONNECT_TIMEOUT_MS = 120_000" not in text:
    text = text.replace(
        "DB_TIMEOUT_SECONDS = 15\n",
        "DB_TIMEOUT_SECONDS = 15\nCDP_CONNECT_TIMEOUT_MS = 120_000\n",
        1,
    )

helper = '''async def connect_browser(playwright: Any) -> Any:\n    info = get_cdp_info()\n    if info is None:\n        raise RuntimeError("9222 未返回有效的 Chrome 调试信息")\n    websocket_url = str(info["webSocketDebuggerUrl"])\n    return await playwright.chromium.connect_over_cdp(\n        websocket_url, timeout=CDP_CONNECT_TIMEOUT_MS\n    )\n\n\n'''
marker = "async def do_crawl(asins: list[str]) -> None:\n"
if helper not in text:
    if marker not in text:
        raise RuntimeError("找不到 do_crawl 插入点")
    text = text.replace(marker, helper + marker, 1)

old_connect = "browser = await playwright.chromium.connect_over_cdp(CDP_ENDPOINT)"
if old_connect in text:
    text = text.replace(old_connect, "browser = await connect_browser(playwright)", 1)

text = text.replace(
    'message="正在连接插件浏览器",',
    'message="正在连接插件浏览器（首次连接最多等待 120 秒）",',
    1,
)

main_path.write_text(text, encoding="utf-8")

Path("tools/apply_runtime_fix.py").unlink(missing_ok=True)
Path(".github/workflows/apply-runtime-fix.yml").unlink(missing_ok=True)
