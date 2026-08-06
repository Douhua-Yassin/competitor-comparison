from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .dashboard_db import DB_PATH, connection, init_dashboard_db

ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE_DIR = ROOT / "data" / "reporting_acceptance"

ENDPOINTS: tuple[dict[str, Any], ...] = (
    {
        "code": "orders",
        "label": "销售订单",
        "metric_codes": ("sales_amount", "units", "order_count"),
        "warning_terms": ("orders", "订单"),
    },
    {
        "code": "after_sales",
        "label": "售后订单",
        "metric_codes": ("refund_amount", "refund_count"),
        "warning_terms": ("after_sales", "售后"),
    },
    {
        "code": "fba_inventory",
        "label": "FBA库存",
        "metric_codes": ("fba_available", "fba_inbound", "fba_reserved"),
        "warning_terms": ("fba_inventory", "库存"),
    },
    {
        "code": "sp_product_report",
        "label": "SP商品广告",
        "metric_codes": (
            "impressions",
            "clicks",
            "ad_spend",
            "ad_sales",
            "ad_orders",
            "ad_units",
        ),
        "warning_terms": ("sp_product_report", "广告"),
    },
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_sync_acceptance(
    db_path: Optional[Path] = None,
    *,
    generated_at: Optional[str] = None,
) -> dict[str, Any]:
    """Build a read-only acceptance view from the latest persisted sync run."""
    path = Path(db_path or DB_PATH)
    init_dashboard_db(path)
    with connection(path) as db:
        run = db.execute(
            "SELECT * FROM lx_sync_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        catalog_count = int(
            db.execute(
                "SELECT COUNT(*) FROM lx_listings WHERE active=1"
            ).fetchone()[0]
        )
        selected_rows = db.execute(
            """
            SELECT l.id, l.sid, l.asin, l.msku, l.product_line,
                   l.responsibility_level, s.store_name, s.country
            FROM lx_listings l
            JOIN lx_stores s ON s.sid=l.sid
            WHERE l.active=1 AND l.responsibility_level IN ('normal','key')
            ORDER BY l.product_line, l.sid, l.msku
            """
        ).fetchall()

        if run is None:
            return {
                "state": "no_sync",
                "generated_at": generated_at or utc_now(),
                "message": "尚无领星同步记录。先同步Listing，设置负责产品后再次同步。",
                "catalog": {
                    "active_listings": catalog_count,
                    "selected_listings": len(selected_rows),
                    "key_listings": sum(
                        1 for row in selected_rows if row["responsibility_level"] == "key"
                    ),
                    "normal_listings": sum(
                        1 for row in selected_rows if row["responsibility_level"] == "normal"
                    ),
                },
                "latest_run": None,
                "endpoints": [],
                "product_lines": [],
                "blocking_issues": [],
                "advisories": ["接口覆盖率表示有数据的Listing比例，不等同于销售或广告是否正常。"],
            }

        details = _json_object(run["details_json"])
        warnings = [str(item) for item in details.get("warnings", []) if str(item).strip()]
        start = date.fromisoformat(run["window_start"])
        end = date.fromisoformat(run["window_end"])
        metrics = db.execute(
            """
            SELECT metric_date, listing_id, metric_code, metric_value, source_endpoint
            FROM lx_daily_metrics
            WHERE metric_date BETWEEN ? AND ?
              AND listing_id IN (
                SELECT id FROM lx_listings
                WHERE active=1 AND responsibility_level IN ('normal','key')
              )
            ORDER BY metric_date, listing_id, source_endpoint, metric_code
            """,
            (start.isoformat(), end.isoformat()),
        ).fetchall()

    selected_ids = {int(row["id"]) for row in selected_rows}
    endpoint_metrics: dict[str, list[Any]] = defaultdict(list)
    for row in metrics:
        endpoint_metrics[str(row["source_endpoint"])].append(row)

    endpoints = [
        _endpoint_acceptance(
            definition,
            endpoint_metrics.get(definition["code"], []),
            selected_ids,
            warnings,
        )
        for definition in ENDPOINTS
    ]
    product_lines = _product_line_acceptance(
        selected_rows,
        endpoint_metrics,
        start,
        end,
    )

    blocking_issues: list[str] = []
    if str(run["status"]) == "failed":
        blocking_issues.append(str(run["message"] or "最近一次同步失败"))
    for warning in warnings:
        lowered = warning.lower()
        if any(term in lowered for term in ("403", "授权", "认证", "appsecret", "白名单")):
            blocking_issues.append(warning)
    run_selected = int(run["selected_count"] or 0)
    if run_selected != len(selected_rows):
        blocking_issues.append(
            f"最近同步时负责产品为 {run_selected} 个，当前设置为 {len(selected_rows)} 个；"
            "请重新同步以使验收口径一致。"
        )

    advisories = [
        "接口覆盖率只表示本周期内有匹配数据的Listing比例；零订单、零售后或无广告活动可能是正常经营结果。",
        "库存接口按每个Listing在周期内最新一条数据计算覆盖，不要求14天每天都有库存记录。",
        "验收报告不读取或输出AppID、AppSecret、访问令牌与请求签名。",
    ]
    if not selected_rows:
        advisories.insert(0, "当前没有重点或普通产品，经营指标同步会被跳过。")

    return {
        "state": "ready",
        "generated_at": generated_at or utc_now(),
        "message": str(run["message"] or ""),
        "catalog": {
            "active_listings": catalog_count,
            "selected_listings": len(selected_rows),
            "key_listings": sum(
                1 for row in selected_rows if row["responsibility_level"] == "key"
            ),
            "normal_listings": sum(
                1 for row in selected_rows if row["responsibility_level"] == "normal"
            ),
            "product_lines": len({row["product_line"] for row in selected_rows}),
            "stores": len({int(row["sid"]) for row in selected_rows}),
        },
        "latest_run": {
            "id": int(run["id"]),
            "status": str(run["status"]),
            "started_at": run["started_at"],
            "finished_at": run["finished_at"],
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "window_days": (end - start).days + 1,
            "catalog_count": int(run["catalog_count"] or 0),
            "selected_count": run_selected,
            "metric_count": int(run["metric_count"] or 0),
            "finalized_count": int(details.get("finalized_count") or 0),
            "warnings": warnings,
        },
        "endpoints": endpoints,
        "product_lines": product_lines,
        "blocking_issues": _deduplicate(blocking_issues),
        "advisories": advisories,
    }


def write_acceptance_report(
    file_format: str = "md",
    db_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> Path:
    normalized = file_format.strip().lower()
    if normalized not in {"md", "json"}:
        raise ValueError("验收报告格式只支持 md 或 json")
    payload = build_sync_acceptance(db_path)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    directory = Path(output_dir or ACCEPTANCE_DIR) / stamp
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"acceptance-report.{normalized}"
    if normalized == "json":
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    else:
        path.write_text(_markdown(payload), encoding="utf-8")
    return path


def _endpoint_acceptance(
    definition: dict[str, Any],
    rows: list[Any],
    selected_ids: set[int],
    warnings: list[str],
) -> dict[str, Any]:
    listing_ids = {int(row["listing_id"]) for row in rows}
    dates = sorted({str(row["metric_date"]) for row in rows})
    metric_codes = sorted({str(row["metric_code"]) for row in rows})
    endpoint_warnings = [
        warning
        for warning in warnings
        if any(term.lower() in warning.lower() for term in definition["warning_terms"])
    ]
    expected = len(selected_ids)
    coverage = (len(listing_ids) / expected) if expected else None
    if endpoint_warnings:
        status = "warning"
        status_label = "接口告警"
    elif not rows:
        status = "empty"
        status_label = "本周期无匹配数据"
    elif expected and len(listing_ids) < expected:
        status = "partial"
        status_label = "部分产品有数据"
    else:
        status = "covered"
        status_label = "已有匹配数据"
    return {
        "code": definition["code"],
        "label": definition["label"],
        "status": status,
        "status_label": status_label,
        "metric_rows": len(rows),
        "listings_with_data": len(listing_ids),
        "selected_listings": expected,
        "coverage_ratio": round(coverage, 4) if coverage is not None else None,
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "metric_codes": metric_codes,
        "expected_metric_codes": list(definition["metric_codes"]),
        "warnings": endpoint_warnings,
    }


def _product_line_acceptance(
    selected_rows: list[Any],
    endpoint_metrics: dict[str, list[Any]],
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    for row in selected_rows:
        grouped[str(row["product_line"] or "未命名产品线")].append(row)

    result: list[dict[str, Any]] = []
    for product_line, listings in sorted(grouped.items()):
        listing_ids = {int(row["id"]) for row in listings}
        endpoint_summary: dict[str, Any] = {}
        for definition in ENDPOINTS:
            rows = [
                row
                for row in endpoint_metrics.get(definition["code"], [])
                if int(row["listing_id"]) in listing_ids
            ]
            endpoint_summary[definition["code"]] = {
                "listings_with_data": len({int(row["listing_id"]) for row in rows}),
                "days_with_data": len({str(row["metric_date"]) for row in rows}),
                "metric_rows": len(rows),
                "latest_date": max(
                    (str(row["metric_date"]) for row in rows),
                    default=None,
                ),
            }
        result.append(
            {
                "product_line": product_line,
                "listing_count": len(listings),
                "key_count": sum(
                    1 for row in listings if row["responsibility_level"] == "key"
                ),
                "normal_count": sum(
                    1 for row in listings if row["responsibility_level"] == "normal"
                ),
                "store_count": len({int(row["sid"]) for row in listings}),
                "countries": sorted(
                    {str(row["country"] or "未识别国家") for row in listings}
                ),
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
                "endpoints": endpoint_summary,
            }
        )
    return result


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _deduplicate(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# 领星经营数据同步验收报告",
        "",
        f"- 生成时间：`{payload['generated_at']}`",
        f"- 状态：`{payload['state']}`",
        f"- 说明：{payload.get('message') or '-'}",
        "",
    ]
    latest = payload.get("latest_run")
    if latest is None:
        lines.extend([payload["message"], ""])
    else:
        catalog = payload["catalog"]
        lines.extend(
            [
                "## 最近一次同步",
                "",
                f"- 运行编号：`{latest['id']}`",
                f"- 运行状态：`{latest['status']}`",
                f"- 时间窗口：`{latest['window_start']}` 至 `{latest['window_end']}`",
                f"- 活跃Listing：{catalog['active_listings']}",
                f"- 当前负责产品：{catalog['selected_listings']}",
                f"- 同步时负责产品：{latest['selected_count']}",
                f"- 写入指标：{latest['metric_count']}",
                f"- 冻结历史：{latest['finalized_count']}",
                "",
                "## 接口覆盖",
                "",
                "| 接口 | 状态 | 有数据Listing/负责Listing | 指标行 | 日期范围 |",
                "|---|---|---:|---:|---|",
            ]
        )
        for endpoint in payload["endpoints"]:
            date_range = (
                f"{endpoint['first_date']} ~ {endpoint['last_date']}"
                if endpoint["first_date"]
                else "-"
            )
            lines.append(
                f"| {endpoint['label']} | {endpoint['status_label']} | "
                f"{endpoint['listings_with_data']}/{endpoint['selected_listings']} | "
                f"{endpoint['metric_rows']} | {date_range} |"
            )
        lines.extend(["", "## 产品线", ""])
        for item in payload["product_lines"]:
            lines.extend(
                [
                    f"### {item['product_line']}",
                    "",
                    f"- Listing：{item['listing_count']}（重点 {item['key_count']}，普通 {item['normal_count']}）",
                    f"- 店铺：{item['store_count']}",
                    f"- 国家：{', '.join(item['countries'])}",
                    f"- 销售订单：{item['endpoints']['orders']['listings_with_data']} 个Listing有数据",
                    f"- 售后订单：{item['endpoints']['after_sales']['listings_with_data']} 个Listing有数据",
                    f"- FBA库存：{item['endpoints']['fba_inventory']['listings_with_data']} 个Listing有数据",
                    f"- SP广告：{item['endpoints']['sp_product_report']['listings_with_data']} 个Listing有数据",
                    "",
                ]
            )
    if payload.get("blocking_issues"):
        lines.extend(["## 阻塞问题", ""])
        lines.extend(f"- {item}" for item in payload["blocking_issues"])
        lines.append("")
    lines.extend(["## 口径说明", ""])
    lines.extend(f"- {item}" for item in payload.get("advisories", []))
    lines.append("")
    return "\n".join(lines)
