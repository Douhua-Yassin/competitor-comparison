from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

from .dashboard_db import DB_PATH, connection
from .targets import METRIC_COLUMNS, init_targets_db

LABELS = {meta[0]: meta[3] for meta in METRIC_COLUMNS.values()}
ADDITIVE = {"sales_amount", "units", "profit", "ad_spend"}


def targets_for_period(
    product_line: str,
    period_type: str,
    start: str,
    end: str,
    summary: dict[str, Any],
    db_path: Optional[Path] = None,
    *,
    products: Optional[list[dict[str, Any]]] = None,
    metric_rows: Optional[list[dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    database = Path(db_path or DB_PATH)
    init_targets_db(database)
    with connection(database) as db:
        rows = [
            dict(row)
            for row in db.execute(
                """
                SELECT * FROM report_targets
                WHERE active=1 AND product_line=? AND period_type=?
                  AND period_start<=? AND period_end>=?
                ORDER BY metric_code, scope_type, id
                """,
                (product_line, period_type, start, end),
            )
        ]

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["metric_code"])].append(row)

    result: list[dict[str, Any]] = []
    product_list = products or []
    all_metric_rows = metric_rows or []
    for metric_code, candidates in grouped.items():
        direct = [row for row in candidates if row["scope_type"] == "product_line"]
        if direct:
            row = direct[-1]
            result.append(
                _payload(
                    row,
                    metric_code,
                    summary.get(metric_code),
                    "产品线目标",
                )
            )
            continue

        for row in [item for item in candidates if item["scope_type"] == "listing"]:
            matched = [product for product in product_list if _matches(row, product)]
            listing_ids = {int(product["id"]) for product in matched}
            actual = _listing_actual(metric_code, listing_ids, all_metric_rows)
            scope_note = _scope_note(row, matched)
            result.append(_payload(row, metric_code, actual, scope_note))
    return result


def _payload(
    row: dict[str, Any],
    metric_code: str,
    actual: Any,
    scope_note: str,
) -> dict[str, Any]:
    target = float(row["target_value"])
    completion = None
    if actual is not None and target != 0:
        completion = float(actual) / target
    direction = str(row["direction"])
    return {
        "metric_code": metric_code,
        "label": LABELS.get(metric_code, metric_code),
        "target": target,
        "actual": actual,
        "completion": completion,
        "unit": str(row["unit"]),
        "direction": direction,
        "status": _target_state(actual, target, direction),
        "scope_note": scope_note,
        "note": row.get("note"),
    }


def _matches(target: dict[str, Any], product: dict[str, Any]) -> bool:
    sid = target.get("sid")
    asin = _norm(target.get("asin"))
    msku = _norm(target.get("msku"))
    if sid is not None and int(product.get("sid") or -1) != int(sid):
        return False
    if asin and _norm(product.get("asin")) != asin:
        return False
    if msku and _norm(product.get("msku")) != msku:
        return False
    return any((sid is not None, asin, msku))


def _listing_actual(
    metric_code: str,
    listing_ids: set[int],
    rows: list[dict[str, Any]],
) -> Optional[float]:
    if not listing_ids:
        return None
    selected = [row for row in rows if int(row["listing_id"]) in listing_ids]
    if metric_code in ADDITIVE:
        values = [float(row["metric_value"]) for row in selected if row["metric_code"] == metric_code]
        return sum(values) if values else None
    if metric_code == "fba_available":
        latest: dict[int, tuple[str, float]] = {}
        for row in selected:
            if row["metric_code"] != "fba_available":
                continue
            listing_id = int(row["listing_id"])
            value = (str(row["metric_date"]), float(row["metric_value"]))
            if listing_id not in latest or value[0] > latest[listing_id][0]:
                latest[listing_id] = value
        return sum(value for _, value in latest.values()) if latest else None
    if metric_code == "tacos":
        sales = _sum_code(selected, "sales_amount")
        spend = _sum_code(selected, "ad_spend")
        return spend / sales if sales not in (None, 0) and spend is not None else None
    if metric_code == "profit_margin":
        sales = _sum_code(selected, "sales_amount")
        profit = _sum_code(selected, "profit")
        return profit / sales if sales not in (None, 0) and profit is not None else None
    values = [float(row["metric_value"]) for row in selected if row["metric_code"] == metric_code]
    return sum(values) / len(values) if values else None


def _sum_code(rows: list[dict[str, Any]], code: str) -> Optional[float]:
    values = [float(row["metric_value"]) for row in rows if row["metric_code"] == code]
    return sum(values) if values else None


def _scope_note(row: dict[str, Any], matched: list[dict[str, Any]]) -> str:
    parts = []
    if row.get("sid") is not None:
        parts.append(f"SID {row['sid']}")
    if row.get("asin"):
        parts.append(f"ASIN {row['asin']}")
    if row.get("msku"):
        parts.append(f"MSKU {row['msku']}")
    identity = " · ".join(parts) or "单品目标"
    if not matched:
        return identity + "（未匹配当前重点Listing）"
    names = [str(item.get("product_name") or item.get("msku") or item.get("asin")) for item in matched]
    return identity + " · " + "、".join(names[:3])


def _target_state(actual: Any, target: float, direction: str) -> str:
    if actual is None:
        return "missing"
    value = float(actual)
    if direction == "higher":
        return "achieved" if value >= target else "in_progress"
    if direction == "lower":
        return "achieved" if value <= target else "exceeded"
    if direction == "budget":
        return "within_budget" if value <= target else "over_budget"
    return "reference"


def _norm(value: Any) -> str:
    return "" if value is None else str(value).strip().upper()
