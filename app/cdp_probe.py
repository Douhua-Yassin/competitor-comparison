"""Read-only Playwright CDP connection probe for diagnostics and CI."""
from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright

from app.main import connect_browser


async def probe() -> None:
    async with async_playwright() as playwright:
        browser = await connect_browser(playwright)
        contexts = len(browser.contexts)
        pages = sum(len(context.pages) for context in browser.contexts)
        print(f"CDP_CONNECTION=SUCCESS contexts={contexts} pages={pages}")


def main() -> None:
    asyncio.run(probe())


if __name__ == "__main__":
    main()
