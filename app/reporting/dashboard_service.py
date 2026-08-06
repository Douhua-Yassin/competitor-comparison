from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

from .dashboard_db import DB_PATH, connection, init_dashboard_db, last_sync, load_notes
from .targets import targets_for_period

WINDOWS: tuple[tuple[str, str, int | None], ...] = (
    ("day", "当日", 1),
    ("3d", "近3日", 3),
    ("7d", "近7日", 7),
    ("14d", "近半月（14日）", 14),
    ("month", "本月", None),
)
SUM_CODES = {
    "sales_amount", "units", "order_count", "refund_amount", "refund_count",
    "impressions", "clicks", "ad_spend", "ad_sales", "ad_orders", "ad_units",
    "profit",
}
LATEST_CODES = {"fba_available", "fba_inbound", "fba_reserved"}
RATIO_CODES = {"ctr", "cpc", "cvr", "acos", "roas", "profit_margin"}


def period_keys(today: Optional[date] = None) -> dict[str, str]:
    current = today or date.today()
    result: dict[str, str] = {}
    for code, _, days in WINDOWS:
        if code == "month":
            result[code] = current.strftime("%Y-%m")
        else:
            start = current - timedelta(days=(days or 1) - 1)
            result[code] = f"{start.isoformat()}:{current.isoformat()}"
    return result


def dashboard(db_path: Optional[Path] = None, today: Optional[date] = None) -> dict[str, Any]:
    path = Path(db_path or DB_PATH)
    init_dashboard_db(path)
    current = today or date.today()
    month_start = current.replace(day=1)
    history_start = min(month_start, current - timedelta(days=27))
    keys = period_keys(current)
    rows, metrics, snapshots = _load_product_data(path, history_start, product_line=None)

    by_line: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_line[str(row["product_line"])].append(row)
    metric_by_listing: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in metrics:
        metric_by_listing[int(row["listing_id"])].append(row)
    snapshot_by_listing = {int(row["listing_id"]): row for row in snapshots}

    modules: list[dict[str, Any]] = []
    for line, products in by_line.items():
        line_metrics: list[dict[str, Any]] = []
        for product in products:
            line_metrics.extend(metric_by_listing[int(product["id"])])
        notes = load_notes(line, keys, path)
        windows = [
            _window_payload(
                code, label, days, current, line_metrics, products,
                snapshot_by_listing, notes[code], keys[code], path,
            )
            for code, label, days in WINDOWS
        ]
        modules.append(_module_payload(line, products, windows))
    return {
        "today": current.isoformat(),
        "last_sync": last_sync(path),
        "product_lines": modules,
        "window_days": 14,
    }


def report_context(
    product_line: str,
    report_type: str,
    db_path: Optional[Path] = None,
    today: Optional[date] = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if report_type not in {"day", "week", "month"}:
        raise ValueError("报告类型必须是 day、week 或 month")
    path = Path(db_path or DB_PATH)
    current = today or date.today()
    if report_type == "day":
        start = current
        label = "当日"
        note_code = "day"
        fallback_code = "day"
    elif report_type == "week":
        start = current - timedelta(days=current.weekday())
        label = "本周"
        note_code = "7d"
        fallback_code = None
    else:
        start = current.replace(day=1)
        label = "本月"
        note_code = "month"
        fallback_code = None

    span = (current - start).days + 1
    history_start = start - timedelta(days=span)
    rows, metrics, snapshots = _load_product_data(path, history_start, product_line=product_line)
    if not rows:
        raise ValueError("当前重点产品线不存在")
    snapshot_by_listing = {int(row["listing_id"]): row for row in snapshots}
    keys = period_keys(current)
    notes = load_notes(product_line, keys, path)
    selected = _window_payload_for_range(
        code=report_type,
        label=label,
        start=start,
        end=current,
        metrics=metrics,
        products=rows,
        snapshots=snapshot_by_listing,
        note=notes[note_code],
        period_key=(
            current.isoformat()
            if report_type == "day"
            else f"{start.isoformat()}:{current.isoformat()}"
            if report_type == "week"
            else current.strftime("%Y-%m")
        ),
        db_path=path,
        target_period_type=report_type,
        fallback_code=fallback_code,
    )
    current_dashboard = dashboard(path, current)
    existing = next(
        (item for item in current_dashboard["product_lines"] if item["product_line"] == product_line),
        None,
    )
    module = existing or _module_payload(product_line, rows, [])
    return module, selected


def _load_product_data(
    path: Path,
    history_start: date,
    *,
    product_line: Optional[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    init_dashboard_db(path)
    with connection(path) as db:
        params: list[Any] = []
        line_clause = ""
        if product_line is not None:
            line_clause = " AND l.product_line=?"
            params.append(product_line)
        rows = [
            dict(row)
            for row in db.execute(
                f"""
                SELECT l.*, s.store_name,
                       COALESCE(l.country, s.country, '未知国家') AS display_country
                FROM lx_listings l JOIN lx_stores s ON s.sid=l.sid
                WHERE l.active=1 AND l.deleted=0
                  AND l.responsibility_level='key'
                  AND l.product_line IS NOT NULL AND TRIM(l.product_line)<>''
                  {line_clause}
                ORDER BY l.product_line, display_country, s.store_name, l.product_name, l.msku
                """,
                params,
            )
        ]
        listing_ids = [int(row["id"]) for row in rows]
        metrics: list[dict[str, Any]] = []
        snapshots: list[dict[str, Any]] = []
        if listing_ids:
            placeholders = ",".join("?" for _ in listing_ids)
            metrics = [
                dict(row)
                for row in db.execute(
                    f"""
                    SELECT metric_date, listing_id, metric_code, metric_value, unit,
                           source_endpoint, is_final
                    FROM lx_daily_metrics
                    WHERE listing_id IN ({placeholders}) AND metric_date>=?
                    ORDER BY metric_date, listing_id, metric_code
                    """,
                    listing_ids + [history_start.isoformat()],
                )
            ]
            snapshots = [
                dict(row)
                for row in db.execute(
                    f"""
                    SELECT s.* FROM lx_listing_snapshots s
                    JOIN (
                      SELECT listing_id, MAX(snapshot_date) AS latest_date
                      FROM lx_listing_snapshots
                      WHERE listing_id IN ({placeholders})
                      GROUP BY listing_id
                    ) latest
                      ON latest.listing_id=s.listing_id AND latest.latest_date=s.snapshot_date
                    """,
                    listing_ids,
                )
            ]
    return rows, metrics, snapshots


def _module_payload(
    line: str,
    products: list[dict[str, Any]],
    windows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "product_line": line,
        "product_count": len(products),
        "products": [
            {
                "id": row["id"],
                "sid": row["sid"],
                "product_name": row["product_name"],
                "asin": row["asin"],
                "msku": row["msku"],
                "store_name": row["store_name"],
                "country": row["display_country"],
            }
            for row in products
        ],
        "windows": windows,
    }


def _window_payload(
    code: str,
    label: str,
    days: Optional[int],
    today: date,
    metrics: list[dict[str, Any]],
    products: list[dict[str, Any]],
    snapshots: dict[int, dict[str, Any]],
    note: dict[str, Any],
    period_key: str,
    db_path: Path,
) -> dict[str, Any]:
    start = today.replace(day=1) if code == "month" else today - timedelta(days=(days or 1) - 1)
    return _window_payload_for_range(
        code=code,
        label=label,
        start=start,
        end=today,
        metrics=metrics,
        products=products,
        snapshots=snapshots,
        note=note,
        period_key=period_key,
        db_path=db_path,
        target_period_type={"day": "day", "month": "month"}.get(code),
        fallback_code=code,
    )


def _window_payload_for_range(
    *,
    code: str,
    label: str,
    start: date,
    end: date,
    metrics: list[dict[str, Any]],
    products: list[dict[str, Any]],
    snapshots: dict[int, dict[str, Any]],
    note: dict[str, Any],
    period_key: str,
    db_path: Path,
    target_period_type: Optional[str],
    fallback_code: Optional[str],
) -> dict[str, Any]:
    prior_end = start - timedelta(days=1)
    span = (end - start).days + 1
    prior_start = prior_end - timedelta(days=span - 1)
    current_rows = [row for row in metrics if start.isoformat() <= row["metric_date"] <= end.isoformat()]
    prior_rows = [row for row in metrics if prior_start.isoformat() <= row["metric_date"] <= prior_end.isoformat()]
    summary = _aggregate(current_rows)
    prior = _aggregate(prior_rows)
    source_note = None
    if not summary.get("sales_amount") and fallback_code in {"day", "7d", "14d"}:
        fallback = _listing_rollup(fallback_code, products, snapshots)
        if fallback:
            summary.update({key: value for key, value in fallback.items() if value is not None})
            source_note = "销售数据来自领星 Listing 当前滚动口径；开始积累逐日数据后将切换为日数据。"
    comparisons: dict[str, Optional[float]] = {}
    for metric_code in ("sales_amount", "units", "profit", "ad_spend", "ad_sales", "refund_amount"):
        comparisons[metric_code] = _change(summary.get(metric_code), prior.get(metric_code))
    series = _series(current_rows, start, end)
    warnings: list[str] = []
    if not current_rows:
        warnings.append("该周期尚无完整逐日经营数据")
    if summary.get("sales_amount") is None:
        warnings.append("销售额数据缺失")
    if summary.get("ad_spend") is None:
        warnings.append("广告数据缺失")
    if summary.get("profit") is None:
        warnings.append("利润接口尚不可用，利润与利润率数据缺失")
    targets = (
        targets_for_period(
            str(products[0]["product_line"]),
            target_period_type,
            start.isoformat(),
            end.isoformat(),
            summary,
            db_path,
        )
        if target_period_type and products
        else []
    )
    return {
        "code": code,
        "label": label,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "period_key": period_key,
        "summary": summary,
        "prior_summary": prior,
        "comparisons": comparisons,
        "series": series,
        "note": note,
        "warnings": warnings,
        "source_note": source_note,
        "targets": targets,
    }


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Optional[float]]:
    grouped: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["metric_code"])].append((str(row["metric_date"]), float(row["metric_value"])))
    result: dict[str, Optional[float]] = {}
    for code in SUM_CODES:
        values = grouped.get(code, [])
        result[code] = sum(value for _, value in values) if values else None
    for code in LATEST_CODES:
        values = grouped.get(code, [])
        result[code] = max(values, key=lambda item: item[0])[1] if values else None
    for code in RATIO_CODES:
        values = grouped.get(code, [])
        result[code] = sum(value for _, value in values) / len(values) if values else None
    sales = result.get("sales_amount")
    spend = result.get("ad_spend")
    result["tacos"] = spend / sales if sales not in (None, 0) and spend is not None else None
    profit = result.get("profit")
    result["profit_margin"] = profit / sales if sales not in (None, 0) and profit is not None else result.get("profit_margin")
    return result


def _series(rows: list[dict[str, Any]], start: date, end: date) -> dict[str, Any]:
    dates = [start + timedelta(days=index) for index in range((end - start).days + 1)]
    codes = ("sales_amount", "units", "profit", "ad_spend", "fba_available")
    values: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        values[(str(row["metric_date"]), str(row["metric_code"]))].append(float(row["metric_value"]))
    result: dict[str, Any] = {"dates": [item.isoformat() for item in dates]}
    for code in codes:
        result[code] = [
            sum(values[(item.isoformat(), code)]) if values[(item.isoformat(), code)] else None
            for item in dates
        ]
    return result


def _listing_rollup(
    code: str,
    products: list[dict[str, Any]],
    snapshots: dict[int, dict[str, Any]],
) -> dict[str, Optional[float]]:
    suffix = {"day": "1d", "7d": "7d", "14d": "14d"}.get(code)
    if suffix is None:
        return {}
    sales_values: list[float] = []
    unit_values: list[float] = []
    stock_values: list[float] = []
    for product in products:
        snapshot = snapshots.get(int(product["id"]))
        if not snapshot:
            continue
        sales = snapshot.get(f"sales_amt_{suffix}")
        units = snapshot.get(f"sales_qty_{suffix}")
        stock = snapshot.get("afn_fulfillable")
        if sales is not None:
            sales_values.append(float(sales))
        if units is not None:
            unit_values.append(float(units))
        if stock is not None:
            stock_values.append(float(stock))
    return {
        "sales_amount": sum(sales_values) if sales_values else None,
        "units": sum(unit_values) if unit_values else None,
        "fba_available": sum(stock_values) if stock_values else None,
    }


def _change(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or previous in (None, 0):
        return None
    return (current - previous) / abs(previous)
