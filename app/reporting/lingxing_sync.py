from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Callable, Iterable, Optional

from app.lingxing_audit.config import AuditSettings
from app.lingxing_audit.serializer import extract_records, to_plain

from .dashboard_db import (
    create_sync_run,
    finalize_before,
    finish_sync_run,
    selected_listing_rows,
    upsert_daily_metric,
    upsert_listings,
    upsert_stores,
)

SYNC_DAYS = 14


@dataclass
class SyncResult:
    catalog_count: int
    selected_count: int
    metric_count: int
    finalized_count: int
    warnings: list[str]


_SYNC_LOCK = asyncio.Lock()
_SYNC_STATUS: dict[str, Any] = {
    "running": False,
    "message": "尚未同步",
    "started_at": None,
    "finished_at": None,
    "catalog_count": 0,
    "selected_count": 0,
    "metric_count": 0,
    "warnings": [],
}


def sync_status() -> dict[str, Any]:
    return dict(_SYNC_STATUS)


async def run_recent_sync(
    api_factory: Optional[Callable[..., Any]] = None,
    settings: Optional[AuditSettings] = None,
) -> SyncResult:
    if _SYNC_LOCK.locked():
        raise RuntimeError("领星数据同步正在运行")
    async with _SYNC_LOCK:
        cfg = settings or AuditSettings.load()
        today = date.today()
        window_start = today - timedelta(days=SYNC_DAYS - 1)
        run_id = create_sync_run(window_start.isoformat(), today.isoformat())
        _SYNC_STATUS.update(
            running=True,
            message="正在刷新领星店铺和 Listing",
            started_at=datetime.now().isoformat(timespec="seconds"),
            finished_at=None,
            catalog_count=0,
            selected_count=0,
            metric_count=0,
            warnings=[],
        )
        catalog_count = 0
        selected_count = 0
        metric_count = 0
        warnings: list[str] = []
        try:
            factory = api_factory or _default_api_factory
            api = factory(
                app_id=cfg.app_id,
                app_secret=cfg.app_secret,
                timeout=cfg.timeout_seconds,
                ignore_timeout=False,
                ignore_api_limit=False,
            )
            async with api:
                stores_payload = await api.basic.Sellers()
                stores = extract_records(to_plain(stores_payload))
                upsert_stores([row for row in stores if isinstance(row, dict)])
                sids = [
                    value
                    for value in (
                        _as_int(row.get("sid") or row.get("seller_id") or row.get("id"))
                        for row in stores
                        if isinstance(row, dict)
                    )
                    if value is not None
                ]
                if cfg.sid is not None:
                    sids = [cfg.sid]
                if not sids:
                    raise RuntimeError("领星没有返回可用店铺 SID")

                listings = await _fetch_raw_listings(api, sorted(set(sids)))
                catalog_count = upsert_listings(listings)
                _SYNC_STATUS.update(
                    catalog_count=catalog_count,
                    message="Listing 已刷新，正在同步最近14天经营数据",
                )

                selected = selected_listing_rows()
                selected_count = len(selected)
                _SYNC_STATUS["selected_count"] = selected_count
                if selected:
                    index = _build_listing_index(selected)
                    selected_sids = sorted({int(row["sid"]) for row in selected})
                    metric_count += await _sync_endpoint(
                        api.sales.Orders,
                        "orders",
                        selected_sids,
                        window_start,
                        today,
                        index,
                        warnings,
                    )
                    metric_count += await _sync_endpoint(
                        api.sales.AfterSalesOrders,
                        "after_sales",
                        selected_sids,
                        window_start,
                        today,
                        index,
                        warnings,
                    )
                    metric_count += await _sync_endpoint(
                        api.warehouse.FbaInventory,
                        "fba_inventory",
                        selected_sids,
                        window_start,
                        today,
                        index,
                        warnings,
                    )
                    profiles: list[dict[str, Any]] = []
                    try:
                        profile_payload = await api.ads.AdProfiles()
                        profiles = [
                            row
                            for row in extract_records(to_plain(profile_payload))
                            if isinstance(row, dict)
                        ]
                    except Exception as exc:  # pragma: no cover - remote behavior
                        warnings.append("广告账号读取失败：" + _safe_error(exc))
                    profile_ids = _selected_profile_ids(profiles, selected_sids)
                    metric_count += await _sync_endpoint(
                        api.ads.SpProductReports,
                        "sp_product_report",
                        selected_sids,
                        window_start,
                        today,
                        index,
                        warnings,
                        profile_ids=profile_ids,
                    )
                finalized_count = finalize_before(window_start.isoformat())

            status = "success" if not warnings else "partial_success"
            message = (
                f"同步完成：Listing {catalog_count}，负责产品 {selected_count}，"
                f"更新指标 {metric_count}，冻结历史 {finalized_count}"
            )
            finish_sync_run(
                run_id,
                status,
                catalog_count,
                selected_count,
                metric_count,
                message,
                {"warnings": warnings, "finalized_count": finalized_count},
            )
            result = SyncResult(
                catalog_count=catalog_count,
                selected_count=selected_count,
                metric_count=metric_count,
                finalized_count=finalized_count,
                warnings=warnings,
            )
            _SYNC_STATUS.update(
                running=False,
                message=message,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                metric_count=metric_count,
                warnings=warnings,
            )
            return result
        except Exception as exc:
            message = "领星同步失败：" + _safe_error(exc)
            finish_sync_run(
                run_id,
                "failed",
                catalog_count,
                selected_count,
                metric_count,
                message,
                {"warnings": warnings},
            )
            _SYNC_STATUS.update(
                running=False,
                message=message,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                metric_count=metric_count,
                warnings=warnings,
            )
            raise


async def _fetch_raw_listings(api: Any, sids: list[int]) -> list[dict[str, Any]]:
    from lingxingapi_httpx.sales import param, route

    offset = 0
    length = 1000
    rows: list[dict[str, Any]] = []
    while True:
        parsed = param.Listings.model_validate(
            {"sids": sids, "deleted": 0, "offset": offset, "length": length}
        )
        payload = await api.sales._request_with_sign(
            "POST",
            route.LISTINGS,
            body=parsed.model_dump_params(),
        )
        plain = to_plain(payload)
        batch = extract_records(plain)
        rows.extend(row for row in batch if isinstance(row, dict))
        total = _as_int(plain.get("total_count")) if isinstance(plain, dict) else None
        if not batch or len(batch) < length or (total is not None and len(rows) >= total):
            break
        offset += length
    return rows


async def _sync_endpoint(
    method: Callable[..., Any],
    endpoint: str,
    sids: list[int],
    start: date,
    end: date,
    listing_index: dict[tuple[str, str], int],
    warnings: list[str],
    profile_ids: Optional[list[int]] = None,
) -> int:
    try:
        payloads = await _call_method_for_window(
            method,
            sids=sids,
            start=start,
            end=end,
            profile_ids=profile_ids or [],
        )
    except Exception as exc:  # pragma: no cover - remote behavior
        warnings.append(f"{endpoint} 同步失败：{_safe_error(exc)}")
        return 0
    inserted = 0
    for payload in payloads:
        inserted += _persist_payload(endpoint, payload, listing_index, start, end)
    return inserted


async def _call_method_for_window(
    method: Callable[..., Any],
    *,
    sids: list[int],
    start: date,
    end: date,
    profile_ids: list[int],
) -> list[Any]:
    signature = inspect.signature(method)
    names = set(signature.parameters)
    dates = [start + timedelta(days=index) for index in range((end - start).days + 1)]
    singular_profiles = "profile_id" in names and "profile_ids" not in names
    per_day = any(name in names for name in ("report_date", "date")) and not any(
        name in names for name in ("start_date", "start_time", "begin_date")
    )
    calls: list[tuple[Optional[date], Optional[int]]] = []
    date_values = dates if per_day else [None]
    profile_values: list[Optional[int]] = (
        profile_ids if singular_profiles and profile_ids else [None]
    )
    for day in date_values:
        for profile_id in profile_values:
            calls.append((day, profile_id))

    results: list[Any] = []
    for day, profile_id in calls:
        offset = 0
        while True:
            kwargs, missing = _build_kwargs(
                signature,
                sids=sids,
                start=start,
                end=end,
                day=day,
                profile_ids=profile_ids,
                profile_id=profile_id,
                offset=offset,
            )
            if missing:
                raise RuntimeError(
                    f"{getattr(method, '__qualname__', method)} 缺少参数：{', '.join(missing)}"
                )
            payload = method(**kwargs)
            if inspect.isawaitable(payload):
                payload = await payload
            plain = to_plain(payload)
            results.append(plain)
            records = extract_records(plain)
            total = _as_int(plain.get("total_count")) if isinstance(plain, dict) else None
            if "offset" not in names or not records or len(records) < 1000:
                break
            if total is not None and offset + len(records) >= total:
                break
            offset += 1000
    return results


def _build_kwargs(
    signature: inspect.Signature,
    *,
    sids: list[int],
    start: date,
    end: date,
    day: Optional[date],
    profile_ids: list[int],
    profile_id: Optional[int],
    offset: int,
) -> tuple[dict[str, Any], list[str]]:
    start_dt = datetime.combine(start, time.min)
    end_dt = datetime.combine(end, time.max)
    candidates: dict[str, Any] = {
        "sids": sids,
        "sid": sids[0] if len(sids) == 1 else sids,
        "seller_ids": sids,
        "seller_id": sids[0] if len(sids) == 1 else sids,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "begin_date": start.isoformat(),
        "report_date": (day or end).isoformat(),
        "date": (day or end).isoformat(),
        "start_time": int(start_dt.timestamp()),
        "end_time": int(end_dt.timestamp()),
        "profile_ids": profile_ids or None,
        "profile_id": profile_id or (profile_ids[0] if len(profile_ids) == 1 else None),
        "offset": offset,
        "length": 1000,
        "page": offset // 1000 + 1,
        "page_size": 1000,
        "date_type": "order_time",
    }
    kwargs: dict[str, Any] = {}
    missing: list[str] = []
    for name, parameter in signature.parameters.items():
        if name == "self" or parameter.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        value = candidates.get(name)
        if value is not None:
            kwargs[name] = value
        elif parameter.default is inspect.Parameter.empty:
            missing.append(name)
    return kwargs, missing


METRIC_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "orders": {
        "sales_amount": ("sales_amount", "order_amount", "item_price", "amount", "revenue"),
        "units": ("quantity", "sales_quantity", "units", "units_ordered"),
        "order_count": ("order_count", "orders"),
    },
    "after_sales": {
        "refund_amount": ("refund_amount", "return_amount", "amount"),
        "refund_count": ("refund_count", "return_count", "quantity"),
    },
    "fba_inventory": {
        "fba_available": (
            "available_quantity", "afn_fulfillable_quantity", "afn_fulfillable",
            "fulfillable_quantity"
        ),
        "fba_inbound": (
            "inbound_quantity", "afn_inbound_shipped_quantity", "afn_inbound_shipped"
        ),
        "fba_reserved": ("reserved_quantity", "afn_reserved_quantity"),
    },
    "sp_product_report": {
        "impressions": ("impressions",),
        "clicks": ("clicks",),
        "ad_spend": ("spend", "cost", "advertising_cost"),
        "ad_sales": (
            "sales", "attributed_sales", "sales_amount", "sales_7d", "sales_14d"
        ),
        "ad_orders": (
            "orders", "attributed_orders", "purchases", "orders_7d", "orders_14d"
        ),
        "ad_units": ("units", "attributed_units_ordered", "units_sold"),
        "ctr": ("ctr", "click_through_rate"),
        "cpc": ("cpc", "cost_per_click"),
        "cvr": ("cvr", "conversion_rate"),
        "acos": ("acos",),
        "roas": ("roas",),
    },
}
DATE_KEYS = (
    "date", "report_date", "stat_date", "data_date", "day", "purchase_date",
    "order_date", "order_time", "refund_date", "return_date",
)


def _persist_payload(
    endpoint: str,
    payload: Any,
    listing_index: dict[tuple[str, str], int],
    start: date,
    end: date,
) -> int:
    aliases = METRIC_ALIASES.get(endpoint, {})
    if not aliases:
        return 0
    grouped: dict[tuple[str, int, str, str], list[float]] = {}
    dimensions_by_key: dict[tuple[str, int, str, str], dict[str, Any]] = {}
    for record in _iter_product_records(payload):
        lowered = {str(key).lower(): value for key, value in record.items()}
        listing_id = _match_listing(lowered, listing_index)
        if listing_id is None:
            continue
        metric_date = _record_date(lowered)
        if metric_date is None:
            if endpoint == "fba_inventory":
                metric_date = end
            else:
                continue
        if metric_date < start or metric_date > end:
            continue
        dimensions = {
            key: value
            for key, value in record.items()
            if str(key).lower()
            in {"sid", "profile_id", "campaign_id", "ad_group_id", "currency", "currency_code"}
        }
        for metric_code, keys in aliases.items():
            value = _first_number(lowered, keys)
            if value is None:
                continue
            unique = (metric_date.isoformat(), listing_id, metric_code, endpoint)
            grouped.setdefault(unique, []).append(value)
            dimensions_by_key[unique] = dimensions

    for (metric_date, listing_id, metric_code, source), values in grouped.items():
        if metric_code in {"ctr", "cpc", "cvr", "acos", "roas"}:
            value = sum(values) / len(values)
        elif metric_code in {"fba_available", "fba_inbound", "fba_reserved"}:
            value = values[-1]
        else:
            value = sum(values)
        upsert_daily_metric(
            metric_date,
            listing_id,
            metric_code,
            value,
            _metric_unit(metric_code),
            source,
            dimensions_by_key.get((metric_date, listing_id, metric_code, source)),
        )
    return len(grouped)


def _iter_product_records(
    value: Any, inherited: Optional[dict[str, Any]] = None
) -> Iterable[dict[str, Any]]:
    inherited = inherited or {}
    if isinstance(value, list):
        for item in value:
            yield from _iter_product_records(item, inherited)
        return
    if not isinstance(value, dict):
        return
    scalar = {
        str(key): item
        for key, item in value.items()
        if not isinstance(item, (dict, list))
    }
    merged = {**inherited, **scalar}
    lowered = {str(key).lower() for key in value}
    if lowered.intersection(
        {"asin", "child_asin", "msku", "seller_sku", "lsku", "local_sku"}
    ):
        yield merged
    for item in value.values():
        if isinstance(item, (dict, list)):
            yield from _iter_product_records(item, merged)


def _build_listing_index(rows: list[dict[str, Any]]) -> dict[tuple[str, str], int]:
    index: dict[tuple[str, str], int] = {}
    for row in rows:
        sid = str(row["sid"])
        listing_id = int(row["id"])
        for value in (row.get("asin"), row.get("msku"), row.get("lsku")):
            text = str(value or "").strip().upper()
            if text:
                index[(sid, text)] = listing_id
    return index


def _match_listing(
    record: dict[str, Any], index: dict[tuple[str, str], int]
) -> Optional[int]:
    sid = str(record.get("sid") or record.get("seller_id") or "").strip()
    identifiers = (
        record.get("asin"), record.get("child_asin"), record.get("msku"),
        record.get("seller_sku"), record.get("lsku"), record.get("local_sku"),
    )
    if sid:
        for value in identifiers:
            text = str(value or "").strip().upper()
            if text and (sid, text) in index:
                return index[(sid, text)]
    matches: set[int] = set()
    for value in identifiers:
        text = str(value or "").strip().upper()
        if not text:
            continue
        matches.update(
            listing_id for (_, code), listing_id in index.items() if code == text
        )
    return next(iter(matches)) if len(matches) == 1 else None


def _record_date(record: dict[str, Any]) -> Optional[date]:
    for key in DATE_KEYS:
        value = record.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        try:
            if text.isdigit() and len(text) >= 10:
                return datetime.fromtimestamp(int(text[:10])).date()
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except (ValueError, OSError):
            try:
                return date.fromisoformat(text[:10])
            except ValueError:
                continue
    return None


def _selected_profile_ids(
    profiles: list[dict[str, Any]], sids: list[int]
) -> list[int]:
    selected: list[int] = []
    all_ids: list[int] = []
    for row in profiles:
        profile_id = _as_int(
            row.get("profile_id") or row.get("profileId") or row.get("id")
        )
        if profile_id is None:
            continue
        all_ids.append(profile_id)
        sid = _as_int(row.get("sid") or row.get("seller_id"))
        if sid is not None and sid in sids:
            selected.append(profile_id)
    return sorted(set(selected or all_ids))


def _first_number(
    record: dict[str, Any], keys: tuple[str, ...]
) -> Optional[float]:
    for key in keys:
        value = record.get(key)
        if value is None or isinstance(value, bool):
            continue
        try:
            text = str(value).replace(",", "").strip()
            percent = text.endswith("%")
            number = float(text.rstrip("%"))
            return number / 100 if percent else number
        except (TypeError, ValueError):
            continue
    return None


def _metric_unit(metric_code: str) -> str:
    if metric_code in {"sales_amount", "refund_amount", "ad_spend", "ad_sales", "cpc"}:
        return "currency"
    if metric_code in {"ctr", "cvr", "acos"}:
        return "ratio"
    if metric_code == "roas":
        return "multiple"
    return "count"


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None and str(value).strip() else None
    except (TypeError, ValueError):
        return None


def _safe_error(exc: Exception) -> str:
    return str(exc).replace("\n", " ")[:500]


def _default_api_factory(**kwargs: Any) -> Any:
    from lingxingapi_httpx import API

    return API(**kwargs)
