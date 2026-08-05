from __future__ import annotations

import json
import sqlite3
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "reporting.db"
DB_TIMEOUT_SECONDS = 15
WRITE_LOCK = threading.RLock()
LEVELS = {"not_mine", "normal", "key"}
WINDOW_CODES = {"day", "3d", "7d", "14d", "month"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=DB_TIMEOUT_SECONDS)
    db.row_factory = sqlite3.Row
    db.execute(f"PRAGMA busy_timeout={DB_TIMEOUT_SECONDS * 1000}")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_dashboard_db(db_path: Optional[Path] = None) -> None:
    path = Path(db_path or DB_PATH)
    with WRITE_LOCK:
        with connection(path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS lx_stores (
                  sid INTEGER PRIMARY KEY,
                  store_name TEXT NOT NULL,
                  country TEXT,
                  marketplace TEXT,
                  active INTEGER NOT NULL DEFAULT 1,
                  raw_json TEXT NOT NULL DEFAULT '{}',
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS lx_listings (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  sid INTEGER NOT NULL,
                  asin TEXT,
                  parent_asin TEXT,
                  msku TEXT NOT NULL,
                  lsku TEXT,
                  fnsku TEXT,
                  product_name TEXT,
                  brand TEXT,
                  title TEXT,
                  thumbnail_url TEXT,
                  country TEXT,
                  currency_code TEXT,
                  fulfillment_channel TEXT,
                  listing_status INTEGER,
                  deleted INTEGER NOT NULL DEFAULT 0,
                  responsibility_level TEXT NOT NULL DEFAULT 'not_mine'
                    CHECK(responsibility_level IN ('not_mine','normal','key')),
                  product_line TEXT,
                  active INTEGER NOT NULL DEFAULT 1,
                  raw_json TEXT NOT NULL DEFAULT '{}',
                  first_seen_at TEXT NOT NULL,
                  last_seen_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  FOREIGN KEY(sid) REFERENCES lx_stores(sid),
                  UNIQUE(sid, msku)
                );

                CREATE INDEX IF NOT EXISTS idx_lx_listings_filter
                  ON lx_listings(country, sid, responsibility_level, active);
                CREATE INDEX IF NOT EXISTS idx_lx_listings_product_line
                  ON lx_listings(product_line, responsibility_level, active);
                CREATE INDEX IF NOT EXISTS idx_lx_listings_asin
                  ON lx_listings(asin, sid);

                CREATE TABLE IF NOT EXISTS lx_listing_snapshots (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  listing_id INTEGER NOT NULL,
                  snapshot_date TEXT NOT NULL,
                  standard_price REAL,
                  sale_price REAL,
                  landed_price REAL,
                  sales_amt_1d REAL,
                  sales_amt_7d REAL,
                  sales_amt_14d REAL,
                  sales_amt_30d REAL,
                  sales_qty_1d REAL,
                  sales_qty_7d REAL,
                  sales_qty_14d REAL,
                  sales_qty_30d REAL,
                  afn_fulfillable REAL,
                  afn_unsellable REAL,
                  afn_inbound_working REAL,
                  afn_inbound_shipped REAL,
                  afn_inbound_receiving REAL,
                  review_count REAL,
                  review_stars REAL,
                  raw_json TEXT NOT NULL DEFAULT '{}',
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  FOREIGN KEY(listing_id) REFERENCES lx_listings(id),
                  UNIQUE(listing_id, snapshot_date)
                );

                CREATE TABLE IF NOT EXISTS lx_daily_metrics (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  metric_date TEXT NOT NULL,
                  listing_id INTEGER NOT NULL,
                  metric_code TEXT NOT NULL,
                  metric_value REAL NOT NULL,
                  unit TEXT,
                  source_endpoint TEXT NOT NULL,
                  is_final INTEGER NOT NULL DEFAULT 0,
                  dimensions_json TEXT NOT NULL DEFAULT '{}',
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  FOREIGN KEY(listing_id) REFERENCES lx_listings(id),
                  UNIQUE(metric_date, listing_id, metric_code, source_endpoint)
                );

                CREATE INDEX IF NOT EXISTS idx_lx_metrics_dashboard
                  ON lx_daily_metrics(listing_id, metric_date, metric_code);
                CREATE INDEX IF NOT EXISTS idx_lx_metrics_final
                  ON lx_daily_metrics(metric_date, is_final);

                CREATE TABLE IF NOT EXISTS lx_sync_runs (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  started_at TEXT NOT NULL,
                  finished_at TEXT,
                  status TEXT NOT NULL,
                  window_start TEXT NOT NULL,
                  window_end TEXT NOT NULL,
                  catalog_count INTEGER NOT NULL DEFAULT 0,
                  selected_count INTEGER NOT NULL DEFAULT 0,
                  metric_count INTEGER NOT NULL DEFAULT 0,
                  message TEXT,
                  details_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS report_notes (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  product_line TEXT NOT NULL,
                  window_code TEXT NOT NULL
                    CHECK(window_code IN ('day','3d','7d','14d','month')),
                  period_key TEXT NOT NULL,
                  content TEXT NOT NULL DEFAULT '',
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  UNIQUE(product_line, window_code, period_key)
                );

                CREATE TABLE IF NOT EXISTS report_note_revisions (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  note_id INTEGER NOT NULL,
                  content TEXT NOT NULL,
                  saved_at TEXT NOT NULL,
                  FOREIGN KEY(note_id) REFERENCES report_notes(id)
                );
                """
            )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def upsert_stores(stores: Iterable[dict[str, Any]], db_path: Optional[Path] = None) -> int:
    path = Path(db_path or DB_PATH)
    init_dashboard_db(path)
    now = utc_now()
    count = 0
    with WRITE_LOCK:
        with connection(path) as db:
            for store in stores:
                sid = _int(store.get("sid") or store.get("seller_id") or store.get("id"))
                if sid is None:
                    continue
                name = _text(
                    store.get("name")
                    or store.get("seller_name")
                    or store.get("store_name")
                    or store.get("account_name")
                ) or f"店铺 {sid}"
                country = _text(store.get("country") or store.get("marketplace_name"))
                marketplace = _text(store.get("marketplace") or store.get("marketplace_id"))
                db.execute(
                    """
                    INSERT INTO lx_stores (
                      sid, store_name, country, marketplace, active,
                      raw_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 1, ?, ?, ?)
                    ON CONFLICT(sid) DO UPDATE SET
                      store_name=excluded.store_name,
                      country=COALESCE(excluded.country, lx_stores.country),
                      marketplace=COALESCE(excluded.marketplace, lx_stores.marketplace),
                      active=1,
                      raw_json=excluded.raw_json,
                      updated_at=excluded.updated_at
                    """,
                    (sid, name, country, marketplace, _json(store), now, now),
                )
                count += 1
    return count


def upsert_listings(listings: Iterable[dict[str, Any]], db_path: Optional[Path] = None) -> int:
    path = Path(db_path or DB_PATH)
    init_dashboard_db(path)
    now = utc_now()
    today = date.today().isoformat()
    seen: set[tuple[int, str]] = set()
    count = 0
    with WRITE_LOCK:
        with connection(path) as db:
            for item in listings:
                sid = _int(item.get("sid"))
                msku = _text(item.get("msku") or item.get("seller_sku"))
                if sid is None or not msku:
                    continue
                key = (sid, msku)
                seen.add(key)
                country = _text(item.get("country") or item.get("marketplace"))
                if country:
                    db.execute(
                        "UPDATE lx_stores SET country=COALESCE(country, ?), updated_at=? WHERE sid=?",
                        (country, now, sid),
                    )
                db.execute(
                    """
                    INSERT INTO lx_listings (
                      sid, asin, parent_asin, msku, lsku, fnsku, product_name,
                      brand, title, thumbnail_url, country, currency_code,
                      fulfillment_channel, listing_status, deleted,
                      responsibility_level, product_line, active, raw_json,
                      first_seen_at, last_seen_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                              'not_mine', NULL, 1, ?, ?, ?, ?)
                    ON CONFLICT(sid, msku) DO UPDATE SET
                      asin=excluded.asin,
                      parent_asin=excluded.parent_asin,
                      lsku=excluded.lsku,
                      fnsku=excluded.fnsku,
                      product_name=excluded.product_name,
                      brand=excluded.brand,
                      title=excluded.title,
                      thumbnail_url=excluded.thumbnail_url,
                      country=excluded.country,
                      currency_code=excluded.currency_code,
                      fulfillment_channel=excluded.fulfillment_channel,
                      listing_status=excluded.listing_status,
                      deleted=excluded.deleted,
                      active=1,
                      raw_json=excluded.raw_json,
                      last_seen_at=excluded.last_seen_at,
                      updated_at=excluded.updated_at
                    """,
                    (
                        sid,
                        _upper(item.get("asin")),
                        _upper(item.get("parent_asin")),
                        msku,
                        _text(item.get("lsku") or item.get("local_sku")),
                        _text(item.get("fnsku")),
                        _text(item.get("product_name") or item.get("local_name")),
                        _text(item.get("brand") or item.get("brand_name")),
                        _text(item.get("title") or item.get("item_name")),
                        _text(item.get("thumbnail_url") or item.get("small_image_url")),
                        country,
                        _text(item.get("currency_code")),
                        _text(item.get("fulfillment_channel")),
                        _int(item.get("status")),
                        _int(item.get("deleted") or item.get("is_delete")) or 0,
                        _json(item),
                        now,
                        now,
                        now,
                    ),
                )
                row = db.execute(
                    "SELECT id, responsibility_level FROM lx_listings WHERE sid=? AND msku=?",
                    (sid, msku),
                ).fetchone()
                if row and row["responsibility_level"] != "not_mine":
                    _upsert_snapshot(db, int(row["id"]), today, item, now)
                count += 1
            if seen:
                placeholders = ",".join("(?,?)" for _ in seen)
                params: list[Any] = []
                for sid, msku in sorted(seen):
                    params.extend([sid, msku])
                db.execute(
                    f"UPDATE lx_listings SET active=0, updated_at=? "
                    f"WHERE (sid, msku) NOT IN ({placeholders})",
                    [now] + params,
                )
    return count


def _upsert_snapshot(
    db: sqlite3.Connection,
    listing_id: int,
    snapshot_date: str,
    item: dict[str, Any],
    now: str,
) -> None:
    fields = (
        "standard_price", "sale_price", "landed_price", "sales_amt_1d",
        "sales_amt_7d", "sales_amt_14d", "sales_amt_30d", "sales_qty_1d",
        "sales_qty_7d", "sales_qty_14d", "sales_qty_30d", "afn_fulfillable",
        "afn_unsellable", "afn_inbound_working", "afn_inbound_shipped",
        "afn_inbound_receiving", "review_count", "review_stars",
    )
    values = [_number(item.get(name)) for name in fields]
    db.execute(
        """
        INSERT INTO lx_listing_snapshots (
          listing_id, snapshot_date, standard_price, sale_price, landed_price,
          sales_amt_1d, sales_amt_7d, sales_amt_14d, sales_amt_30d,
          sales_qty_1d, sales_qty_7d, sales_qty_14d, sales_qty_30d,
          afn_fulfillable, afn_unsellable, afn_inbound_working,
          afn_inbound_shipped, afn_inbound_receiving, review_count,
          review_stars, raw_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(listing_id, snapshot_date) DO UPDATE SET
          standard_price=excluded.standard_price,
          sale_price=excluded.sale_price,
          landed_price=excluded.landed_price,
          sales_amt_1d=excluded.sales_amt_1d,
          sales_amt_7d=excluded.sales_amt_7d,
          sales_amt_14d=excluded.sales_amt_14d,
          sales_amt_30d=excluded.sales_amt_30d,
          sales_qty_1d=excluded.sales_qty_1d,
          sales_qty_7d=excluded.sales_qty_7d,
          sales_qty_14d=excluded.sales_qty_14d,
          sales_qty_30d=excluded.sales_qty_30d,
          afn_fulfillable=excluded.afn_fulfillable,
          afn_unsellable=excluded.afn_unsellable,
          afn_inbound_working=excluded.afn_inbound_working,
          afn_inbound_shipped=excluded.afn_inbound_shipped,
          afn_inbound_receiving=excluded.afn_inbound_receiving,
          review_count=excluded.review_count,
          review_stars=excluded.review_stars,
          raw_json=excluded.raw_json,
          updated_at=excluded.updated_at
        """,
        [listing_id, snapshot_date] + values + [_json(item), now, now],
    )


def update_listing_scope(
    listing_id: int,
    responsibility_level: str,
    product_line: Optional[str],
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    if responsibility_level not in LEVELS:
        raise ValueError("无效的产品档位")
    path = Path(db_path or DB_PATH)
    init_dashboard_db(path)
    line = _text(product_line)
    now = utc_now()
    with WRITE_LOCK:
        with connection(path) as db:
            row = db.execute("SELECT * FROM lx_listings WHERE id=?", (listing_id,)).fetchone()
            if row is None:
                raise ValueError("产品不存在")
            if responsibility_level != "not_mine" and not line:
                line = _text(row["product_name"]) or _text(row["title"]) or row["asin"] or row["msku"]
            if responsibility_level == "not_mine":
                line = None
            db.execute(
                "UPDATE lx_listings SET responsibility_level=?, product_line=?, updated_at=? WHERE id=?",
                (responsibility_level, line, now, listing_id),
            )
            updated = db.execute("SELECT * FROM lx_listings WHERE id=?", (listing_id,)).fetchone()
    return dict(updated)


def list_settings_products(db_path: Optional[Path] = None) -> dict[str, Any]:
    path = Path(db_path or DB_PATH)
    init_dashboard_db(path)
    with connection(path) as db:
        rows = [
            dict(row)
            for row in db.execute(
                """
                SELECT l.*, s.store_name, COALESCE(l.country, s.country, '未知国家') AS display_country
                FROM lx_listings l
                JOIN lx_stores s ON s.sid=l.sid
                WHERE l.active=1 AND l.deleted=0
                ORDER BY display_country, s.store_name, l.product_name, l.msku
                """
            )
        ]
    countries = sorted({row["display_country"] for row in rows})
    stores = sorted(
        ({"sid": row["sid"], "store_name": row["store_name"], "country": row["display_country"]} for row in rows),
        key=lambda item: (item["country"], item["store_name"], item["sid"]),
    )
    unique_stores: list[dict[str, Any]] = []
    seen: set[int] = set()
    for store in stores:
        if store["sid"] not in seen:
            seen.add(store["sid"])
            unique_stores.append(store)
    return {"countries": countries, "stores": unique_stores, "products": rows}


def selected_listing_rows(db_path: Optional[Path] = None) -> list[dict[str, Any]]:
    path = Path(db_path or DB_PATH)
    init_dashboard_db(path)
    with connection(path) as db:
        return [
            dict(row)
            for row in db.execute(
                """
                SELECT l.*, s.store_name
                FROM lx_listings l JOIN lx_stores s ON s.sid=l.sid
                WHERE l.active=1 AND l.deleted=0
                  AND l.responsibility_level IN ('normal','key')
                ORDER BY l.sid, l.product_line, l.msku
                """
            )
        ]


def upsert_daily_metric(
    metric_date: str,
    listing_id: int,
    metric_code: str,
    metric_value: float,
    unit: Optional[str],
    source_endpoint: str,
    dimensions: Optional[dict[str, Any]] = None,
    db_path: Optional[Path] = None,
) -> None:
    path = Path(db_path or DB_PATH)
    now = utc_now()
    with WRITE_LOCK:
        with connection(path) as db:
            db.execute(
                """
                INSERT INTO lx_daily_metrics (
                  metric_date, listing_id, metric_code, metric_value, unit,
                  source_endpoint, is_final, dimensions_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                ON CONFLICT(metric_date, listing_id, metric_code, source_endpoint)
                DO UPDATE SET metric_value=excluded.metric_value,
                              unit=excluded.unit,
                              dimensions_json=excluded.dimensions_json,
                              updated_at=excluded.updated_at
                WHERE lx_daily_metrics.is_final=0
                """,
                (
                    metric_date,
                    listing_id,
                    metric_code,
                    metric_value,
                    unit,
                    source_endpoint,
                    _json(dimensions or {}),
                    now,
                    now,
                ),
            )


def finalize_before(cutoff_date: str, db_path: Optional[Path] = None) -> int:
    path = Path(db_path or DB_PATH)
    with WRITE_LOCK:
        with connection(path) as db:
            cursor = db.execute(
                "UPDATE lx_daily_metrics SET is_final=1, updated_at=? WHERE metric_date<? AND is_final=0",
                (utc_now(), cutoff_date),
            )
            return int(cursor.rowcount)


def create_sync_run(window_start: str, window_end: str, db_path: Optional[Path] = None) -> int:
    path = Path(db_path or DB_PATH)
    init_dashboard_db(path)
    with WRITE_LOCK:
        with connection(path) as db:
            cursor = db.execute(
                """
                INSERT INTO lx_sync_runs (started_at, status, window_start, window_end)
                VALUES (?, 'running', ?, ?)
                """,
                (utc_now(), window_start, window_end),
            )
            return int(cursor.lastrowid)


def finish_sync_run(
    run_id: int,
    status: str,
    catalog_count: int,
    selected_count: int,
    metric_count: int,
    message: str,
    details: Optional[dict[str, Any]] = None,
    db_path: Optional[Path] = None,
) -> None:
    path = Path(db_path or DB_PATH)
    with WRITE_LOCK:
        with connection(path) as db:
            db.execute(
                """
                UPDATE lx_sync_runs
                SET finished_at=?, status=?, catalog_count=?, selected_count=?,
                    metric_count=?, message=?, details_json=?
                WHERE id=?
                """,
                (
                    utc_now(),
                    status,
                    catalog_count,
                    selected_count,
                    metric_count,
                    message,
                    _json(details or {}),
                    run_id,
                ),
            )


def last_sync(db_path: Optional[Path] = None) -> Optional[dict[str, Any]]:
    path = Path(db_path or DB_PATH)
    init_dashboard_db(path)
    with connection(path) as db:
        row = db.execute("SELECT * FROM lx_sync_runs ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        return None
    result = dict(row)
    result["details"] = json.loads(result.pop("details_json") or "{}")
    return result


def save_note(
    product_line: str,
    window_code: str,
    period_key: str,
    content: str,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    if window_code not in WINDOW_CODES:
        raise ValueError("无效的记录周期")
    line = _text(product_line)
    if not line:
        raise ValueError("产品线不能为空")
    path = Path(db_path or DB_PATH)
    init_dashboard_db(path)
    now = utc_now()
    with WRITE_LOCK:
        with connection(path) as db:
            row = db.execute(
                "SELECT * FROM report_notes WHERE product_line=? AND window_code=? AND period_key=?",
                (line, window_code, period_key),
            ).fetchone()
            if row is None:
                cursor = db.execute(
                    """
                    INSERT INTO report_notes (
                      product_line, window_code, period_key, content, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (line, window_code, period_key, content, now, now),
                )
                note_id = int(cursor.lastrowid)
            else:
                note_id = int(row["id"])
                if row["content"] != content:
                    db.execute(
                        "INSERT INTO report_note_revisions (note_id, content, saved_at) VALUES (?, ?, ?)",
                        (note_id, row["content"], now),
                    )
                db.execute(
                    "UPDATE report_notes SET content=?, updated_at=? WHERE id=?",
                    (content, now, note_id),
                )
            saved = db.execute("SELECT * FROM report_notes WHERE id=?", (note_id,)).fetchone()
    return dict(saved)


def load_notes(product_line: str, period_keys: dict[str, str], db_path: Optional[Path] = None) -> dict[str, Any]:
    path = Path(db_path or DB_PATH)
    init_dashboard_db(path)
    result: dict[str, Any] = {}
    with connection(path) as db:
        for code, key in period_keys.items():
            row = db.execute(
                "SELECT content, updated_at FROM report_notes WHERE product_line=? AND window_code=? AND period_key=?",
                (product_line, code, key),
            ).fetchone()
            result[code] = dict(row) if row else {"content": "", "updated_at": None}
    return result


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _upper(value: Any) -> Optional[str]:
    text = _text(value)
    return text.upper() if text else None


def _int(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None and str(value).strip() else None
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None
