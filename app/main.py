"""Small Amazon US price monitor with an optional SellerSprite browser profile."""
from __future__ import annotations

import asyncio
import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from bs4 import BeautifulSoup
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "monitor.db"
DEFAULT_INPUT = next((p for p in ROOT.glob("*.xlsx") if not p.name.startswith("~$")), ROOT / "products.xlsx")
ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")
BROWSER_PROFILE_DIR = DATA_DIR / "browser-profile"
BROWSER_HEADLESS = False
SELLER_SPRITE_WAIT_SECONDS = 30
DELIVERY_ZIP_CODE = "90210"
status: dict[str, Any] = {"running": False, "message": "idle", "success": 0, "failed": 0,
                          "browser_status": "browser_not_started", "seller_sprite_status": "unknown",
                          "delivery_status": "unknown"}

app = FastAPI(title="Amazon Price Monitor")
app.mount("/static", StaticFiles(directory=ROOT / "app" / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "app" / "templates")


def connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def init_db() -> None:
    with connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS products (
          asin TEXT PRIMARY KEY, brand TEXT, size_raw TEXT, size_normalized TEXT, is_self BOOLEAN,
          input_rating_text TEXT, input_rating_value REAL, input_review_count INTEGER, input_price REAL,
          enabled BOOLEAN NOT NULL DEFAULT 1, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL);
        CREATE TABLE IF NOT EXISTS crawl_records (
          id INTEGER PRIMARY KEY AUTOINCREMENT, asin TEXT NOT NULL, record_date DATE NOT NULL,
          captured_at DATETIME NOT NULL, price REAL, price_text TEXT, sales_text TEXT, rank_text TEXT,
          rating_value REAL, review_count INTEGER, crawl_status TEXT NOT NULL, error_message TEXT,
          source TEXT NOT NULL CHECK(source IN ('live','fixture')), data_source TEXT,
          seller_sprite_status TEXT, delivery_status TEXT, FOREIGN KEY(asin) REFERENCES products(asin));
        CREATE INDEX IF NOT EXISTS idx_crawl_asin_date ON crawl_records(asin, record_date, captured_at);
        """)
        existing = {r[1] for r in db.execute("PRAGMA table_info(crawl_records)")}
        for column in ("data_source TEXT", "seller_sprite_status TEXT", "delivery_status TEXT"):
            if column.split()[0] not in existing:
                db.execute("ALTER TABLE crawl_records ADD COLUMN " + column)


def normalize_size(value: Any) -> Optional[str]:
    if value is None or not str(value).strip(): return None
    text = re.sub(r"(?i)(?<=\d)\s*(?:feet|ft)\b", "", str(value).strip())
    text = re.sub(r"[＊*×xX]", "×", text)
    parts = [part.strip() for part in text.split("×") if part.strip()]
    return "×".join(parts) + " ft" if parts else None


def parse_rating(value: Any) -> tuple[Optional[str], Optional[float], Optional[int]]:
    if value is None or not str(value).strip(): return None, None, None
    text = str(value).strip(); nums = re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))
    return text, (float(nums[0]) if nums else None), (int(float(nums[1])) if len(nums) > 1 else None)


def as_price(value: Any) -> Optional[float]:
    found = re.search(r"\d+(?:,\d{3})*(?:\.\d+)?", str(value or ""))
    return float(found.group().replace(",", "")) if found else None


def import_workbook(path: Path) -> dict[str, Any]:
    init_db(); rows: dict[str, tuple[Any, ...]] = {}
    for ws in load_workbook(path, data_only=True, read_only=True).worksheets:
        for row in ws.iter_rows(min_col=1, max_col=6, values_only=True):
            asin = str(row[2] or "").strip().upper()
            if ASIN_RE.fullmatch(asin): rows[asin] = row
    now = datetime.now().isoformat(timespec="seconds")
    with connection() as db:
        for asin, row in rows.items():
            rating_text, rating_value, reviews = parse_rating(row[3])
            own = str(row[5] or "").strip().lower() in {chr(26159), "yes", "true", "1", "y"}
            db.execute("""INSERT INTO products (asin,brand,size_raw,size_normalized,is_self,input_rating_text,input_rating_value,input_review_count,input_price,enabled,created_at,updated_at)
              VALUES (?,?,?,?,?,?,?,?,?,1,?,?) ON CONFLICT(asin) DO UPDATE SET brand=excluded.brand,size_raw=excluded.size_raw,size_normalized=excluded.size_normalized,is_self=excluded.is_self,input_rating_text=excluded.input_rating_text,input_rating_value=excluded.input_rating_value,input_review_count=excluded.input_review_count,input_price=excluded.input_price,updated_at=excluded.updated_at""",
              (asin, str(row[0] or "").strip() or None, str(row[1] or "").strip() or None, normalize_size(row[1]), own, rating_text, rating_value, reviews, as_price(row[4]), now, now))
    return {"imported": len(rows), "asins": sorted(rows)}


def parse_amazon_html(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser"); body = soup.get_text(" ", strip=True); lower = body.lower()
    if "captcha" in lower or "robot check" in lower: return {"crawl_status": "blocked_or_captcha", "error_message": "Amazon CAPTCHA"}
    if "page not found" in lower or "sorry! we couldn" in lower: return {"crawl_status": "page_not_found", "error_message": "Amazon page not found"}
    def first(selectors: list[str]) -> Optional[str]:
        for selector in selectors:
            node = soup.select_one(selector)
            if node and node.get_text(" ", strip=True): return node.get_text(" ", strip=True)
        return None
    price_text = first([".priceToPay .a-offscreen", "#corePrice_feature_div .a-offscreen", "#priceblock_ourprice", "#priceblock_dealprice", ".a-price .a-offscreen"])
    rating = first(["#acrPopover", "[data-hook='rating-out-of-text']"]); reviews = first(["#acrCustomerReviewText", "[data-hook='total-review-count']"])
    detail = first(["#productDetails_detailBullets_sections1", "#detailBullets_feature_div", "#productDetails_db_sections"])
    rank = re.search(r"#[\d,]+\s+in\s+[^#\n]{1,120}", detail or body, re.I)
    rating_num = re.search(r"(\d(?:\.\d)?)\s+out of 5", rating or body, re.I)
    review_num = re.search(r"[\d,]+", reviews or "")
    price = as_price(price_text)
    if price is None: return {"crawl_status": "failed", "error_message": "Price was not publicly displayed"}
    return {"price": price, "price_text": price_text, "sales_text": first(["#social-proofing-faceout-title-tk_bought", "#social-proofing-faceout-title", "#social-proofing-as-title"]), "rank_text": rank.group(0).strip() if rank else None, "rating_value": float(rating_num.group(1)) if rating_num else None, "review_count": int(review_num.group().replace(",", "")) if review_num else None, "crawl_status": "success", "error_message": None}


def parse_seller_sprite_html(html: str, asin: str) -> dict[str, Any]:
    """Parse the extension without volatile Vue IDs or absolute XPath."""
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one('[name="seller-sprite-extension-quick-view-%s"]' % asin) or soup.select_one('[name^="seller-sprite-extension-quick-view-"]')
    if not root: return {"seller_sprite_status": "unavailable"}
    def field(label: str) -> Optional[str]:
        node = next((n for n in root.select(".word-title") if n.get_text(" ", strip=True) == label), None)
        if not node: return None
        container = node.parent
        text = container.get_text(" ", strip=True).replace(label, "", 1).strip(" :：")
        return text or None
    rating = field("评分(评分数):")
    rating_value, review_count = None, None
    if rating:
        match = re.search(r"(\d(?:\.\d+)?)\s*[（(]\s*([\d,]+)", rating)
        if match: rating_value, review_count = float(match.group(1)), int(match.group(2).replace(",", ""))
    ranks = []
    for item in root.select("p.bsr-list-item"):
        text = item.get_text(" ", strip=True); match = re.search(r"#([\d,]+)\s+in\s+(.+)", text, re.I)
        if match: ranks.append({"rank": int(match.group(1).replace(",", "")), "category": match.group(2).strip(), "text": "#%s in %s" % (match.group(1), match.group(2).strip())})
    sales = field("近30天销量(父体):")
    return {"seller_sprite_status": "loaded", "asin": asin, "brand": field("品牌:"), "price": as_price(field("价格:")), "price_text": field("价格:"), "rating_value": rating_value, "review_count": review_count, "parent_sales": None if not sales or sales.upper() == "N/A" else sales, "rank_list": ranks, "rank_text": ranks[-1]["text"] if ranks else None, "size": field("Size:")}


async def set_delivery_location(page: Any) -> str:
    """Set US delivery only when Amazon currently reports China."""
    try:
        location = page.locator("#glow-ingress-line2")
        current = await location.inner_text(timeout=5000)
        if DELIVERY_ZIP_CODE in current or "china" not in current.lower(): return "delivery_already_set"
        opener = page.locator("#nav-global-location-popover-link")
        if await opener.count() == 0: opener = page.locator("#glow-ingress-block")
        await opener.click(timeout=5000)
        zip_input = page.locator("#GLUXZipUpdateInput"); await zip_input.wait_for(state="visible", timeout=10000)
        await zip_input.fill(DELIVERY_ZIP_CODE); await page.locator("#GLUXZipUpdate input.a-button-input").click(timeout=5000)
        await page.wait_for_function("""zip => { const a=document.querySelector('#GLUXHiddenSuccessSelectedAddressPlaceholder'); const b=document.querySelector('#glow-ingress-line2'); return (a && a.textContent.includes(zip)) || (b && (!b.textContent.includes('China') || b.textContent.includes(zip))); }""", DELIVERY_ZIP_CODE, timeout=15000)
        close = page.locator("#GLUXConfirmClose")
        if await close.is_visible(): await close.click()
        await page.reload(wait_until="domcontentloaded", timeout=30000)
        return "delivery_set_90210"
    except Exception as exc:
        return "delivery_location_failed: " + str(exc)[:180]


async def crawl_product(asin: str, context: Any, delivery_state: dict[str, str]) -> dict[str, Any]:
    captured_at = datetime.now().isoformat(timespec="seconds"); result: dict[str, Any]
    try:
        page = await context.new_page(); await page.goto("https://www.amazon.com/dp/" + asin, wait_until="domcontentloaded", timeout=30000)
        if delivery_state["value"] == "unknown":
            delivery_state["value"] = await set_delivery_location(page); status["delivery_status"] = delivery_state["value"]
        amazon = parse_amazon_html(await page.content())
        sprite_status, sprite, waited = "unavailable", {}, 0
        root = page.locator('[name="seller-sprite-extension-quick-view-%s"]' % asin)
        started = datetime.now()
        try:
            await root.wait_for(state="attached", timeout=SELLER_SPRITE_WAIT_SECONDS * 1000)
            sprite = parse_seller_sprite_html(await root.evaluate("el => el.outerHTML"), asin); sprite_status = sprite["seller_sprite_status"]
        except Exception: sprite = {"seller_sprite_status": "unavailable"}
        waited = round((datetime.now() - started).total_seconds(), 1)
        await page.close()
        if amazon.get("crawl_status") != "success": result = amazon
        else:
            result = dict(amazon); result["seller_sprite_status"] = sprite_status; result["seller_sprite_wait_seconds"] = waited
            if sprite_status == "loaded":
                for key in ("price", "price_text", "rating_value", "review_count"):
                    if sprite.get(key) is not None:
                        if result.get(key) is not None and result[key] != sprite[key]: result.setdefault("warnings", []).append("source_conflict:" + key)
                        result[key] = sprite[key]
                if sprite.get("parent_sales") is not None: result["sales_text"] = sprite["parent_sales"]
                if sprite.get("rank_text") is not None: result["rank_text"] = sprite["rank_text"]
                result["crawl_status"] = "success" if sprite.get("parent_sales") is not None and sprite.get("rank_text") is not None else "partial_success"
                result["data_source"] = "seller_sprite+amazon"
            else:
                result.update(crawl_status="partial_success", data_source="amazon_public", warnings=["seller_sprite_unavailable"])
        status["seller_sprite_status"] = sprite_status
    except Exception as exc: result = {"crawl_status": "failed", "error_message": str(exc)[:500], "seller_sprite_status": "unavailable", "data_source": "none"}
    result.update(asin=asin, captured_at=captured_at, delivery_status=delivery_state["value"])
    if result.get("warnings"): result["error_message"] = "; ".join(result["warnings"])
    save_record(result, "live"); return result


def save_record(record: dict[str, Any], source: str) -> None:
    with connection() as db:
        db.execute("""INSERT INTO crawl_records (asin,record_date,captured_at,price,price_text,sales_text,rank_text,rating_value,review_count,crawl_status,error_message,source,data_source,seller_sprite_status,delivery_status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (record["asin"],record["captured_at"][:10],record["captured_at"],record.get("price"),record.get("price_text"),record.get("sales_text"),record.get("rank_text"),record.get("rating_value"),record.get("review_count"),record["crawl_status"],record.get("error_message"),source,record.get("data_source"),record.get("seller_sprite_status"),record.get("delivery_status")))


async def do_crawl() -> None:
    init_db(); status.update(running=True, message="opening_browser", success=0, failed=0, browser_status="opening_browser", seller_sprite_status="unknown", delivery_status="unknown")
    with connection() as db: asins = [r[0] for r in db.execute("SELECT asin FROM products WHERE enabled=1")]
    delivery_state = {"value": "unknown"}
    try:
        from playwright.async_api import async_playwright
        BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(str(BROWSER_PROFILE_DIR), headless=BROWSER_HEADLESS, viewport={"width": 1280, "height": 1000})
            status["browser_status"] = "running"
            try:
                for asin in asins:
                    result = await crawl_product(asin, context, delivery_state)
                    if result["crawl_status"] in {"success", "partial_success"}: status["success"] += 1
                    else: status["failed"] += 1
            finally: await context.close()
    except Exception as exc:
        status["browser_status"] = "launch_failed"
        for asin in asins:
            record = {"asin": asin, "captured_at": datetime.now().isoformat(timespec="seconds"), "crawl_status": "failed", "error_message": "browser_launch_failed: " + str(exc)[:400], "delivery_status": delivery_state["value"], "data_source": "none"}; save_record(record, "live"); status["failed"] += 1
    status.update(running=False, message="completed", browser_status="browser_not_started")


def table_data(range_name: str) -> dict[str, Any]:
    with connection() as db:
        products = [dict(r) for r in db.execute("SELECT * FROM products ORDER BY size_normalized,is_self DESC,brand,asin")]
        dates = [r[0] for r in db.execute("SELECT DISTINCT record_date FROM crawl_records ORDER BY record_date DESC")]
        if range_name in {"3d", "7d"}: dates = [d for d in dates if d >= (date.today()-timedelta(days=int(range_name[0])-1)).isoformat()]
        records = [dict(r) for r in db.execute("SELECT * FROM crawl_records ORDER BY captured_at DESC")]
    cells = {}
    for p in products:
        for d in dates:
            rows = [r for r in records if r["asin"] == p["asin"] and r["record_date"] == d]; good = [r for r in rows if r["crawl_status"] in {"success", "partial_success"}]
            if good: cells[p["asin"],d] = good[0]
            elif rows: cells[p["asin"],d] = rows[0]
    baseline = {(p["size_normalized"],d): min(cells[p["asin"],d]["price"] for p in products if p["is_self"] and p["size_normalized"] == p0["size_normalized"] and (p["asin"],d) in cells and cells[p["asin"],d]["price"] is not None) for p0 in products for d in dates if any(p["is_self"] and p["size_normalized"] == p0["size_normalized"] and (p["asin"],d) in cells and cells[p["asin"],d]["price"] is not None for p in products)}
    for p in products:
        p["cells"] = []
        for d in dates:
            r = cells.get((p["asin"],d)); tone = "neutral"; base = baseline.get((p["size_normalized"],d))
            if r and not p["is_self"] and r["price"] is not None and base is not None: tone = "low" if r["price"] < base else "high" if r["price"] > base else "neutral"
            p["cells"].append({"record": r, "tone": tone})
    return {"dates": dates, "products": products, "status": status}


@app.on_event("startup")
def startup() -> None:
    init_db()
    with connection() as db: empty = db.execute("SELECT count(*) FROM products").fetchone()[0] == 0
    if empty and DEFAULT_INPUT.exists(): import_workbook(DEFAULT_INPUT)

@app.get("/", response_class=HTMLResponse)
def home(request: Request): return templates.TemplateResponse(request, "index.html", {"table": table_data("all")})

@app.post("/api/import")
async def api_import(file: Optional[UploadFile] = File(None)):
    path = DEFAULT_INPUT if file is None else DATA_DIR / "uploaded.xlsx"
    if file is not None:
        if not file.filename or not file.filename.lower().endswith(".xlsx"): raise HTTPException(400, "Only .xlsx is supported")
        path.write_bytes(await file.read())
    if not path.exists(): raise HTTPException(404, "Default workbook not found")
    return import_workbook(path)

@app.post("/api/crawl")
async def api_crawl():
    if status["running"]: raise HTTPException(409, "Crawl already running")
    asyncio.create_task(do_crawl()); return {"started": True}

@app.get("/api/status")
def api_status(): return status

@app.get("/api/table")
def api_table(range: str = "all"):
    if range not in {"all", "3d", "7d"}: raise HTTPException(400, "range must be all, 3d, or 7d")
    return table_data(range)
