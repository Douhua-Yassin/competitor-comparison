from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .dashboard_db import DB_PATH, connection, init_dashboard_db
from .sync_acceptance import (
    ACCEPTANCE_DIR,
    build_sync_acceptance as build_base_acceptance,
)

_AUTHORIZATION_HEADER = re.compile(
    r"(?i)\bauthorization\b(\s*[:=]\s*)([^\r\n,;]+)"
)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b("
    r"app[_-]?id|app[_-]?secret|client[_-]?secret|api[_-]?key|"
    r"access[_-]?token|refresh[_-]?token|id[_-]?token|token|"
    r"signature|sign"
    r")\b(\s*[:=]\s*)"
    r"(\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_BEARER_TOKEN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_URL_SECRET = re.compile(
    r"(?i)([?&](?:app_id|app_secret|client_secret|api_key|access_token|"
    r"refresh_token|id_token|token|signature|sign)=)([^&#\s]+)"
)
_BLOCKING_WARNING_TERMS = (
    "403",
    "401",
    "授权",
    "认证",
    "白名单",
    "429",
    "限流",
    "rate limit",
    "timeout",
    "超时",
    "network",
    "网络",
)


def build_sync_acceptance(
    db_path: Optional[Path] = None,
    *,
    generated_at: Optional[str] = None,
    runtime_running: Optional[bool] = None,
) -> dict[str, Any]:
    """Return the public acceptance payload with runtime-state and secret hardening."""
    path = Path(db_path or DB_PATH)
    payload = build_base_acceptance(path, generated_at=generated_at)
    payload = _sanitize_value(payload)
    latest = payload.get("latest_run")
    if not isinstance(latest, dict):
        return payload

    if latest.get("status") == "running":
        if runtime_running is None:
            try:
                from .lingxing_sync import sync_status

                runtime_running = bool(sync_status().get("running"))
            except Exception:  # pragma: no cover - defensive import boundary
                runtime_running = False
        if runtime_running:
            payload.update(
                state="syncing",
                message="领星数据同步仍在运行，验收结果将在同步完成后生成。",
                endpoints=[],
                product_lines=[],
                blocking_issues=[],
            )
            payload.setdefault("advisories", []).insert(
                0,
                "当前页面不会使用同步中的半成品指标进行覆盖率判断。",
            )
            return payload
        payload.update(
            state="interrupted",
            message="检测到上一次同步未正常结束，请重新执行同步。",
            endpoints=[],
            product_lines=[],
            blocking_issues=["上一次同步记录仍为running，但当前没有同步任务在运行。"],
        )
        return _sanitize_value(payload)

    blocking = list(payload.get("blocking_issues") or [])
    for warning in latest.get("warnings") or []:
        lowered = str(warning).lower()
        if any(term in lowered for term in _BLOCKING_WARNING_TERMS):
            blocking.append(str(warning))

    finished_at = _parse_datetime(latest.get("finished_at"))
    changed = _scope_changes_after(path, finished_at)
    if changed:
        preview = "、".join(changed[:5])
        suffix = "等" if len(changed) > 5 else ""
        blocking.append(
            f"最近同步完成后又修改了负责范围：{preview}{suffix}；请重新同步。"
        )
    payload["blocking_issues"] = _deduplicate(blocking)
    return _sanitize_value(payload)


def write_acceptance_report(
    file_format: str = "md",
    db_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> Path:
    """Atomically write a sanitized acceptance report."""
    normalized = str(file_format or "").strip().lower()
    if normalized not in {"md", "json"}:
        raise ValueError("验收报告格式只支持 md 或 json")
    payload = build_sync_acceptance(db_path)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    directory = Path(output_dir or ACCEPTANCE_DIR) / stamp
    directory.mkdir(parents=True, exist_ok=False)
    final_path = directory / f"acceptance-report.{normalized}"
    temporary_path = directory / f".{final_path.name}.tmp"
    try:
        if normalized == "json":
            content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        else:
            content = _markdown(payload)
        temporary_path.write_text(content, encoding="utf-8")
        temporary_path.replace(final_path)
        return final_path
    except Exception:
        temporary_path.unlink(missing_ok=True)
        shutil.rmtree(directory, ignore_errors=True)
        raise


def _scope_changes_after(path: Path, finished_at: Optional[datetime]) -> list[str]:
    if finished_at is None:
        return []
    init_dashboard_db(path)
    with connection(path) as db:
        rows = db.execute(
            """
            SELECT msku, product_line, updated_at
            FROM lx_listings
            WHERE active=1 AND deleted=0
              AND responsibility_level IN ('normal','key')
              AND product_line IS NOT NULL AND TRIM(product_line)<>''
            """
        ).fetchall()
    changed: list[str] = []
    for row in rows:
        updated_at = _parse_datetime(row["updated_at"])
        if updated_at is not None and updated_at > finished_at:
            changed.append(f"{row['product_line']} / {row['msku']}")
    return sorted(set(changed))


def _parse_datetime(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _sanitize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, str):
        return _sanitize_text(value)
    return value


def _sanitize_text(value: Any) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    text = _AUTHORIZATION_HEADER.sub(
        lambda match: f"Authorization{match.group(1)}***redacted***",
        text,
    )
    text = _BEARER_TOKEN.sub("Bearer ***redacted***", text)
    text = _SENSITIVE_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}{match.group(2)}***redacted***",
        text,
    )
    return _URL_SECRET.sub(lambda match: f"{match.group(1)}***redacted***", text)


def _deduplicate(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _sanitize_text(value)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# 领星经营数据同步验收报告",
        "",
        f"- 生成时间：`{_md(payload.get('generated_at'))}`",
        f"- 状态：`{_md(payload.get('state'))}`",
        f"- 说明：{_md(payload.get('message') or '-')}",
        "",
    ]
    latest = payload.get("latest_run")
    if isinstance(latest, dict):
        catalog = payload.get("catalog") or {}
        lines.extend(
            [
                "## 最近一次同步",
                "",
                f"- 运行编号：`{latest.get('id', '-')}`",
                f"- 运行状态：`{_md(latest.get('status'))}`",
                f"- 时间窗口：`{_md(latest.get('window_start'))}` 至 `{_md(latest.get('window_end'))}`",
                f"- 活跃Listing：{catalog.get('active_listings', 0)}",
                f"- 当前负责产品：{catalog.get('selected_listings', 0)}",
                f"- 同步时负责产品：{latest.get('selected_count', 0)}",
                f"- 写入指标：{latest.get('metric_count', 0)}",
                "",
                "## 接口覆盖",
                "",
                "| 接口 | 状态 | 有数据Listing/负责Listing | 指标行 | 日期范围 |",
                "|---|---|---:|---:|---|",
            ]
        )
        for endpoint in payload.get("endpoints") or []:
            date_range = (
                f"{endpoint.get('first_date')} ~ {endpoint.get('last_date')}"
                if endpoint.get("first_date")
                else "-"
            )
            lines.append(
                f"| {_md(endpoint.get('label'))} | {_md(endpoint.get('status_label'))} | "
                f"{endpoint.get('listings_with_data', 0)}/{endpoint.get('selected_listings', 0)} | "
                f"{endpoint.get('metric_rows', 0)} | {_md(date_range)} |"
            )
        lines.extend(["", "## 产品线", ""])
        for item in payload.get("product_lines") or []:
            endpoints = item.get("endpoints") or {}
            lines.extend(
                [
                    f"### {_md(item.get('product_line'))}",
                    "",
                    f"- Listing：{item.get('listing_count', 0)}（重点 {item.get('key_count', 0)}，普通 {item.get('normal_count', 0)}）",
                    f"- 店铺：{item.get('store_count', 0)}",
                    f"- 国家：{_md(', '.join(item.get('countries') or []))}",
                    f"- 销售订单：{_endpoint_count(endpoints, 'orders')} 个Listing有数据",
                    f"- 售后订单：{_endpoint_count(endpoints, 'after_sales')} 个Listing有数据",
                    f"- FBA库存：{_endpoint_count(endpoints, 'fba_inventory')} 个Listing有数据",
                    f"- SP广告：{_endpoint_count(endpoints, 'sp_product_report')} 个Listing有数据",
                    "",
                ]
            )
    if payload.get("blocking_issues"):
        lines.extend(["## 阻塞问题", ""])
        lines.extend(f"- {_md(item)}" for item in payload["blocking_issues"])
        lines.append("")
    lines.extend(["## 口径说明", ""])
    lines.extend(f"- {_md(item)}" for item in payload.get("advisories", []))
    lines.append("")
    return "\n".join(lines)


def _endpoint_count(endpoints: dict[str, Any], code: str) -> int:
    value = endpoints.get(code) or {}
    return int(value.get("listings_with_data") or 0)


def _md(value: Any) -> str:
    return (
        _sanitize_text(value)
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("`", "\\`")
    )
