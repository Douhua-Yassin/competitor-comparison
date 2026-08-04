from __future__ import annotations

import asyncio
import importlib.metadata
import inspect
import json
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .catalog import PROBES
from .config import AuditSettings, DEFAULT_BASE_URL
from .models import AuditReport, ProbeDefinition, ProbeResult
from .serializer import extract_fields, extract_records, redact, to_plain


@dataclass
class AuditContext:
    sid: int | None = None
    profile_id: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"sid": self.sid, "profile_id": self.profile_id}


class AuditRunner:
    def __init__(
        self,
        settings: AuditSettings,
        api_factory: Callable[..., Any] | None = None,
        probes: tuple[ProbeDefinition, ...] = PROBES,
    ) -> None:
        self.settings = settings
        self.api_factory = api_factory or _default_api_factory
        self.probes = probes
        self.context = AuditContext(sid=settings.sid)

    async def run(self) -> AuditReport:
        started = datetime.now(timezone.utc)
        run_id = started.astimezone().strftime("%Y%m%d-%H%M%S")
        run_dir = self.settings.output_dir / run_id
        sample_dir = run_dir / "samples"
        sample_dir.mkdir(parents=True, exist_ok=True)
        warnings: list[str] = []
        if self.settings.base_url != DEFAULT_BASE_URL:
            warnings.append(
                "当前审计 SDK 固定使用官方 OpenAPI 地址；LINGXING_BASE_URL 已记录但未覆盖 SDK 内部地址。"
            )

        api = self.api_factory(
            app_id=self.settings.app_id,
            app_secret=self.settings.app_secret,
            timeout=self.settings.timeout_seconds,
            ignore_timeout=False,
            ignore_api_limit=False,
        )
        results: list[ProbeResult] = []
        completed: dict[str, ProbeResult] = {}
        try:
            async with api:
                for probe in self.probes:
                    unmet = [key for key in probe.depends_on if key not in completed]
                    if unmet:
                        result = ProbeResult(
                            key=probe.key,
                            category=probe.category,
                            label=probe.label,
                            method_path=probe.method_path,
                            status="skipped",
                            message=f"依赖探针尚未执行：{', '.join(unmet)}",
                        )
                    else:
                        result = await self._run_probe(api, probe, sample_dir)
                    results.append(result)
                    completed[probe.key] = result
        except Exception as exc:
            if not results:
                results.append(
                    ProbeResult(
                        key="client",
                        category="认证",
                        label="API客户端初始化",
                        method_path="API",
                        status=_classify_error(exc),
                        error_type=type(exc).__name__,
                        message=_safe_error(exc),
                    )
                )

        finished = datetime.now(timezone.utc)
        summary: dict[str, int] = {}
        for result in results:
            summary[result.status] = summary.get(result.status, 0) + 1
        report = AuditReport(
            run_id=run_id,
            started_at=started.isoformat(),
            finished_at=finished.isoformat(),
            settings=self.settings.public_summary(),
            sdk_version=_sdk_version(),
            summary=summary,
            results=results,
            context=self.context.as_dict(),
            warnings=warnings,
        )
        _write_report(run_dir, report)
        _write_latest_pointer(self.settings.output_dir, run_id)
        return report

    async def _run_probe(self, api: Any, probe: ProbeDefinition, sample_dir: Path) -> ProbeResult:
        started = time.perf_counter()
        try:
            method = _resolve_path(api, probe.method_path)
        except AttributeError as exc:
            return ProbeResult(
                key=probe.key,
                category=probe.category,
                label=probe.label,
                method_path=probe.method_path,
                status="sdk_method_missing",
                error_type=type(exc).__name__,
                message=str(exc),
            )

        params, required = _build_parameters(method, probe.params, self.context, self.settings)
        if required:
            return ProbeResult(
                key=probe.key,
                category=probe.category,
                label=probe.label,
                method_path=probe.method_path,
                status="needs_parameters",
                parameters_used=redact(params),
                required_parameters=required,
                message="SDK方法需要额外参数；已记录签名，未发送请求。",
            )
        try:
            payload = method(**params)
            if inspect.isawaitable(payload):
                payload = await payload
            plain = redact(to_plain(payload))
            records = extract_records(plain)
            sample_file = sample_dir / f"{probe.key}.json"
            sample_file.write_text(
                json.dumps(plain, ensure_ascii=False, indent=2)[:500_000],
                encoding="utf-8",
            )
            self._update_context(probe.key, plain)
            return ProbeResult(
                key=probe.key,
                category=probe.category,
                label=probe.label,
                method_path=probe.method_path,
                status="success",
                duration_ms=int((time.perf_counter() - started) * 1000),
                sample_count=len(records),
                fields=extract_fields(plain),
                parameters_used=redact(params),
                sample_file=str(sample_file),
            )
        except Exception as exc:
            return ProbeResult(
                key=probe.key,
                category=probe.category,
                label=probe.label,
                method_path=probe.method_path,
                status=_classify_error(exc),
                duration_ms=int((time.perf_counter() - started) * 1000),
                parameters_used=redact(params),
                error_type=type(exc).__name__,
                message=_safe_error(exc),
            )

    def _update_context(self, key: str, payload: Any) -> None:
        records = extract_records(payload)
        if key == "sellers" and self.context.sid is None:
            self.context.sid = _first_int(records, ("sid", "seller_id", "id"))
        if key == "ad_profiles" and self.context.profile_id is None:
            self.context.profile_id = _first_int(records, ("profile_id", "profileId", "id"))


def _default_api_factory(**kwargs: Any) -> Any:
    from lingxingapi_httpx import API

    return API(**kwargs)


def _resolve_path(root: Any, path: str) -> Any:
    current = root
    for part in path.split("."):
        current = getattr(current, part)
    if not callable(current):
        raise AttributeError(f"{path} 不是可调用方法")
    return current


def _build_parameters(
    method: Callable[..., Any],
    defaults: dict[str, Any],
    context: AuditContext,
    settings: AuditSettings,
) -> tuple[dict[str, Any], list[str]]:
    signature = inspect.signature(method)
    today = date.today()
    start = today - timedelta(days=settings.lookback_days)
    start_ts = int(datetime.combine(start, datetime.min.time()).timestamp())
    end_ts = int(datetime.combine(today, datetime.max.time()).timestamp())
    candidates: dict[str, Any] = {
        **defaults,
        "sid": context.sid,
        "seller_id": context.sid,
        "seller_ids": [context.sid] if context.sid is not None else None,
        "sids": [context.sid] if context.sid is not None else None,
        "profile_id": context.profile_id,
        "profile_ids": [context.profile_id] if context.profile_id is not None else None,
        "start_date": start.isoformat(),
        "end_date": today.isoformat(),
        "report_date": (today - timedelta(days=1)).isoformat(),
        "start_time": start_ts,
        "end_time": end_ts,
    }
    params: dict[str, Any] = {}
    required: list[str] = []
    accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values())
    for name, parameter in signature.parameters.items():
        if name == "self" or parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        value = candidates.get(name)
        if value is not None:
            params[name] = value
        elif parameter.default is inspect.Parameter.empty:
            required.append(name)
    if accepts_kwargs:
        for name, value in defaults.items():
            if value is not None:
                params.setdefault(name, value)
    return params, required


def _first_int(records: list[Any], keys: tuple[str, ...]) -> int | None:
    for record in records:
        if not isinstance(record, dict):
            continue
        for key in keys:
            value = record.get(key)
            try:
                if value is not None:
                    return int(value)
            except (TypeError, ValueError):
                continue
    return None


def _classify_error(exc: Exception) -> str:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "secret" in name or "appid" in name or "credential" in text or "invalid client" in text:
        return "authentication_failed"
    if "permission" in name or "forbidden" in text or "403" in text or "white" in text or "白名单" in text:
        return "permission_denied"
    if "timeout" in name or "timeout" in text:
        return "timeout"
    if "parameter" in name or "validation" in name or "参数" in text:
        return "parameter_error"
    if "internet" in name or "connect" in name or "network" in text or "dns" in text:
        return "network_error"
    if "limit" in name or "429" in text or "限流" in text:
        return "rate_limited"
    return "error"


def _safe_error(exc: Exception) -> str:
    return str(exc)[:2000]


def _sdk_version() -> str | None:
    try:
        return importlib.metadata.version("lingxingapi-httpx")
    except importlib.metadata.PackageNotFoundError:
        return None


def _write_report(run_dir: Path, report: AuditReport) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "audit-report.json").write_text(
        json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "audit-report.md").write_text(_render_markdown(report), encoding="utf-8")


def _write_latest_pointer(output_dir: Path, run_id: str) -> None:
    (output_dir / "latest.txt").write_text(run_id, encoding="utf-8")


def _render_markdown(report: AuditReport) -> str:
    lines = [
        "# 领星 OpenAPI 第一阶段接口盘点",
        "",
        f"- 运行编号：`{report.run_id}`",
        f"- SDK版本：`{report.sdk_version or '未安装'}`",
        f"- 开始时间：{report.started_at}",
        f"- 完成时间：{report.finished_at}",
        "",
        "## 汇总",
        "",
    ]
    for status, count in sorted(report.summary.items()):
        lines.append(f"- `{status}`：{count}")
    if report.warnings:
        lines.extend(["", "## 警告", ""] + [f"- {item}" for item in report.warnings])
    lines.extend([
        "",
        "## 接口结果",
        "",
        "| 类别 | 接口 | 状态 | 样本数 | 字段数 | 说明 |",
        "|---|---|---:|---:|---:|---|",
    ])
    for result in report.results:
        message = (result.message or "").replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {result.category} | {result.label} (`{result.method_path}`) | {result.status} | "
            f"{result.sample_count if result.sample_count is not None else ''} | {len(result.fields)} | {message} |"
        )
    lines.extend([
        "",
        "## 已发现的上下文",
        "",
        f"```json\n{json.dumps(report.context, ensure_ascii=False, indent=2)}\n```",
        "",
    ])
    return "\n".join(lines)


async def run_audit(settings: AuditSettings | None = None) -> AuditReport:
    return await AuditRunner(settings or AuditSettings.load()).run()


def run_audit_sync(settings: AuditSettings | None = None) -> AuditReport:
    return asyncio.run(run_audit(settings))
