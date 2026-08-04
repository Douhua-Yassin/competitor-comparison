from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
REPORTING_DB_PATH = DATA_DIR / "reporting.db"
MONITOR_DB_PATH = DATA_DIR / "monitor.db"
DB_TIMEOUT_SECONDS = 15
WRITE_LOCK = threading.RLock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = Path(db_path or REPORTING_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=DB_TIMEOUT_SECONDS)
    db.row_factory = sqlite3.Row
    db.execute(f"PRAGMA busy_timeout = {DB_TIMEOUT_SECONDS * 1000}")
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_reporting_db(
    db_path: Optional[Path] = None,
    monitor_db_path: Optional[Path] = None,
) -> None:
    path = Path(db_path or REPORTING_DB_PATH)
    with WRITE_LOCK:
        with connection(path) as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS report_runs (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  run_type TEXT NOT NULL,
                  source_run_id TEXT NOT NULL,
                  started_at TEXT,
                  finished_at TEXT,
                  status TEXT NOT NULL,
                  summary_json TEXT NOT NULL DEFAULT '{}',
                  created_at TEXT NOT NULL,
                  UNIQUE(run_type, source_run_id)
                );

                CREATE TABLE IF NOT EXISTS endpoint_availability (
                  endpoint_key TEXT PRIMARY KEY,
                  category TEXT,
                  label TEXT,
                  status TEXT NOT NULL,
                  message TEXT,
                  last_run_id INTEGER,
                  updated_at TEXT NOT NULL,
                  FOREIGN KEY(last_run_id) REFERENCES report_runs(id)
                );

                CREATE TABLE IF NOT EXISTS raw_snapshots (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  run_id INTEGER NOT NULL,
                  endpoint_key TEXT NOT NULL,
                  category TEXT,
                  label TEXT,
                  status TEXT NOT NULL,
                  sample_count INTEGER,
                  captured_at TEXT NOT NULL,
                  payload_json TEXT,
                  payload_sha256 TEXT,
                  sample_file TEXT,
                  error_message TEXT,
                  FOREIGN KEY(run_id) REFERENCES report_runs(id),
                  UNIQUE(run_id, endpoint_key)
                );

                CREATE TABLE IF NOT EXISTS report_product_lines (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  monitor_line_id INTEGER,
                  name TEXT NOT NULL UNIQUE,
                  sheet_order INTEGER NOT NULL DEFAULT 0,
                  active INTEGER NOT NULL DEFAULT 1,
                  responsibility_level TEXT NOT NULL DEFAULT 'not_mine'
                    CHECK(responsibility_level IN ('not_mine','normal','key')),
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS report_products (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  product_line_id INTEGER NOT NULL,
                  asin TEXT NOT NULL,
                  brand TEXT,
                  size_normalized TEXT,
                  is_self INTEGER NOT NULL DEFAULT 0,
                  active INTEGER NOT NULL DEFAULT 1,
                  responsibility_level TEXT
                    CHECK(responsibility_level IS NULL OR responsibility_level IN ('not_mine','normal','key')),
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  FOREIGN KEY(product_line_id) REFERENCES report_product_lines(id),
                  UNIQUE(product_line_id, asin)
                );

                CREATE TABLE IF NOT EXISTS targets (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  period_type TEXT NOT NULL
                    CHECK(period_type IN ('day','week','month','quarter','year')),
                  period_start TEXT NOT NULL,
                  period_end TEXT NOT NULL,
                  product_line_id INTEGER NOT NULL,
                  asin TEXT,
                  metric_code TEXT NOT NULL,
                  target_value REAL NOT NULL,
                  unit TEXT,
                  version INTEGER NOT NULL,
                  status TEXT NOT NULL DEFAULT 'active'
                    CHECK(status IN ('active','superseded','cancelled')),
                  note TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  FOREIGN KEY(product_line_id) REFERENCES report_product_lines(id)
                );

                CREATE INDEX IF NOT EXISTS idx_targets_lookup
                  ON targets(product_line_id, asin, period_type, period_start, period_end, metric_code, status);

                CREATE TABLE IF NOT EXISTS action_log (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  product_line_id INTEGER NOT NULL,
                  asin TEXT,
                  action_date TEXT NOT NULL,
                  action_type TEXT NOT NULL,
                  title TEXT NOT NULL,
                  content TEXT NOT NULL,
                  reason TEXT,
                  expected_result TEXT,
                  review_date TEXT,
                  status TEXT NOT NULL DEFAULT 'planned'
                    CHECK(status IN ('planned','in_progress','completed','cancelled')),
                  actual_result TEXT,
                  source TEXT NOT NULL DEFAULT 'user'
                    CHECK(source IN ('user','ai')),
                  confirmed INTEGER NOT NULL DEFAULT 1,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  FOREIGN KEY(product_line_id) REFERENCES report_product_lines(id)
                );

                CREATE INDEX IF NOT EXISTS idx_action_lookup
                  ON action_log(product_line_id, action_date, status, review_date);

                CREATE TABLE IF NOT EXISTS daily_metrics (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  metric_date TEXT NOT NULL,
                  product_line_id INTEGER,
                  asin TEXT,
                  sku TEXT,
                  metric_code TEXT NOT NULL,
                  metric_value REAL NOT NULL,
                  unit TEXT,
                  source_endpoint TEXT NOT NULL,
                  source_snapshot_id INTEGER NOT NULL,
                  dimensions_json TEXT NOT NULL DEFAULT '{}',
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(product_line_id) REFERENCES report_product_lines(id),
                  FOREIGN KEY(source_snapshot_id) REFERENCES raw_snapshots(id)
                );

                CREATE INDEX IF NOT EXISTS idx_daily_metrics_lookup
                  ON daily_metrics(metric_date, product_line_id, asin, metric_code);
                CREATE INDEX IF NOT EXISTS idx_daily_metrics_source
                  ON daily_metrics(source_snapshot_id);
                """
            )
    sync_catalog_from_monitor(path, monitor_db_path)


def sync_catalog_from_monitor(
    db_path: Optional[Path] = None,
    monitor_db_path: Optional[Path] = None,
) -> dict[str, int]:
    reporting_path = Path(db_path or REPORTING_DB_PATH)
    monitor_path = Path(monitor_db_path or MONITOR_DB_PATH)
    if not monitor_path.exists():
        return {"product_lines": 0, "products": 0}

    try:
        with sqlite3.connect(monitor_path) as monitor:
            monitor.row_factory = sqlite3.Row
            tables = {
                row[0]
                for row in monitor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if not {"product_lines", "product_line_items"}.issubset(tables):
                return {"product_lines": 0, "products": 0}
            lines = list(
                monitor.execute(
                    """
                    SELECT id, name, sheet_order, active
                    FROM product_lines
                    ORDER BY sheet_order, id
                    """
                )
            )
            items = list(
                monitor.execute(
                    """
                    SELECT product_line_id, asin, brand, size_normalized, is_self, active
                    FROM product_line_items
                    ORDER BY product_line_id, item_order, asin
                    """
                )
            )
    except sqlite3.Error:
        return {"product_lines": 0, "products": 0}

    now = utc_now()
    line_id_map: dict[int, int] = {}
    with WRITE_LOCK:
        with connection(reporting_path) as db:
            for row in lines:
                db.execute(
                    """
                    INSERT INTO report_product_lines (
                      monitor_line_id, name, sheet_order, active,
                      responsibility_level, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'not_mine', ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                      monitor_line_id=excluded.monitor_line_id,
                      sheet_order=excluded.sheet_order,
                      active=excluded.active,
                      updated_at=excluded.updated_at
                    """,
                    (
                        row["id"],
                        row["name"],
                        row["sheet_order"],
                        row["active"],
                        now,
                        now,
                    ),
                )
                report_line = db.execute(
                    "SELECT id FROM report_product_lines WHERE name=?",
                    (row["name"],),
                ).fetchone()
                if report_line:
                    line_id_map[int(row["id"])] = int(report_line["id"])

            seen: set[tuple[int, str]] = set()
            for row in items:
                report_line_id = line_id_map.get(int(row["product_line_id"]))
                if report_line_id is None:
                    continue
                key = (report_line_id, str(row["asin"]))
                seen.add(key)
                db.execute(
                    """
                    INSERT INTO report_products (
                      product_line_id, asin, brand, size_normalized,
                      is_self, active, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(product_line_id, asin) DO UPDATE SET
                      brand=excluded.brand,
                      size_normalized=excluded.size_normalized,
                      is_self=excluded.is_self,
                      active=excluded.active,
                      updated_at=excluded.updated_at
                    """,
                    (
                        report_line_id,
                        row["asin"],
                        row["brand"],
                        row["size_normalized"],
                        row["is_self"],
                        row["active"],
                        now,
                        now,
                    ),
                )

            for report_line_id in line_id_map.values():
                existing = list(
                    db.execute(
                        "SELECT id, asin FROM report_products WHERE product_line_id=?",
                        (report_line_id,),
                    )
                )
                for product in existing:
                    if (report_line_id, product["asin"]) not in seen:
                        db.execute(
                            "UPDATE report_products SET active=0, updated_at=? WHERE id=?",
                            (now, product["id"]),
                        )

    return {"product_lines": len(line_id_map), "products": len(seen)}
