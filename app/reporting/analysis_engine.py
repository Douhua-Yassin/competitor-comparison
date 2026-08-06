from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from dotenv import dotenv_values

ANALYSIS_KEYS = (
    "executive_summary",
    "performance",
    "causes",
    "risks",
    "actions",
    "support_needed",
)
NUMBER_PATTERN = re.compile(r"(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d+)?%?")
DEFAULT_MODEL = "deepseek-v4-flash"
JSON_EXAMPLE = {
    "executive_summary": ["总体结论"],
    "performance": ["表现判断"],
    "causes": ["变化原因"],
    "risks": ["主要风险"],
    "actions": ["下一步动作"],
    "support_needed": ["需要的支持"],
}


@dataclass(frozen=True)
class AnalysisResult:
    analysis: dict[str, list[str]]
    source: str
    warning: Optional[str] = None
    raw_response: Optional[str] = None


def generate_analysis(
    context: dict[str, Any],
    fallback: dict[str, list[str]],
    root: Path,
    *,
    post: Optional[Callable[..., Any]] = None,
) -> AnalysisResult:
    settings = deepseek_settings(root)
    if not settings["api_key"]:
        return AnalysisResult(fallback, "rules", "未配置DeepSeek，使用规则版分析")

    prompt = (
        "根据下面的确定数据、目标和人工记录生成亚马逊经营报告分析。"
        "不得创造、修改或补齐任何数字；缺失数据必须明确写缺失。"
        "不得猜测未提供的促销、广告操作、库存到货或市场事件。"
        "将人工记录中的已执行操作、判断、原因、计划和所需支持融入分析。"
        "只返回JSON对象，不要使用Markdown。每个字段必须是字符串数组。"
        "JSON结构示例："
        + json.dumps(JSON_EXAMPLE, ensure_ascii=False)
        + "\n\n确定上下文："
        + json.dumps(context, ensure_ascii=False, default=str)
    )
    try:
        if post is None:
            import httpx

            post = httpx.post
        response = post(
            settings["base_url"].rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {settings['api_key']}"},
            json={
                "model": settings["model"],
                "messages": [
                    {
                        "role": "system",
                        "content": "你是严谨的亚马逊经营分析助手，只能使用用户提供的数据和记录，并严格输出JSON。",
                    },
                    {"role": "user", "content": prompt},
                ],
                "thinking": {"type": "disabled"},
                "response_format": {"type": "json_object"},
                "temperature": 0.1,
                "max_tokens": settings["max_tokens"],
            },
            timeout=settings["timeout"],
        )
        response.raise_for_status()
        payload = response.json()
        choice = payload["choices"][0]
        if choice.get("finish_reason") == "length":
            raise ValueError("DeepSeek输出达到max_tokens并被截断")
        content = choice["message"].get("content")
        if not content or not str(content).strip():
            raise ValueError("DeepSeek返回空content")
        raw = str(content)
        parsed = json.loads(raw)
        validated = _validate_analysis(parsed)
        _reject_unseen_numbers(validated, context)
        return AnalysisResult(validated, "deepseek", raw_response=raw)
    except Exception as exc:
        warning = f"DeepSeek分析失败，已使用规则版：{type(exc).__name__}: {_safe_message(exc)}"
        return AnalysisResult(fallback, "rules_fallback", warning)


def deepseek_settings(root: Path) -> dict[str, Any]:
    env_path = root / ".env"
    values = dotenv_values(env_path) if env_path.exists() else {}

    def read(name: str, default: str = "") -> str:
        return str(os.getenv(name) or values.get(name) or default).strip()

    timeout = _bounded_int(read("DEEPSEEK_TIMEOUT_SECONDS", "90"), 90, 10, 300)
    max_tokens = _bounded_int(read("DEEPSEEK_MAX_TOKENS", "4096"), 4096, 512, 16384)
    return {
        "api_key": read("DEEPSEEK_API_KEY"),
        "base_url": read("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "model": read("DEEPSEEK_MODEL", DEFAULT_MODEL),
        "timeout": timeout,
        "max_tokens": max_tokens,
    }


def _bounded_int(value: str, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except ValueError:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _validate_analysis(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        raise ValueError("DeepSeek返回值不是JSON对象")
    result: dict[str, list[str]] = {}
    for key in ANALYSIS_KEYS:
        items = value.get(key)
        if not isinstance(items, list):
            raise ValueError(f"DeepSeek字段{key}不是数组")
        cleaned: list[str] = []
        for item in items[:12]:
            if not isinstance(item, str):
                raise ValueError(f"DeepSeek字段{key}包含非文本内容")
            text = re.sub(r"\s+", " ", item).strip()
            if not text:
                continue
            if len(text) > 800:
                raise ValueError(f"DeepSeek字段{key}单条文本过长")
            cleaned.append(text)
        result[key] = cleaned
    return result


def _reject_unseen_numbers(
    analysis: dict[str, list[str]],
    context: dict[str, Any],
) -> None:
    raw_tokens = NUMBER_PATTERN.findall(json.dumps(context, ensure_ascii=False, default=str))
    allowed = {_normalize_number(token) for token in raw_tokens}
    for token in raw_tokens:
        if token.endswith("%"):
            continue
        try:
            number = float(token.replace(",", ""))
        except ValueError:
            continue
        if -1 <= number <= 1:
            allowed.add(_normalize_number(f"{number * 100}%"))
    output = "\n".join(item for values in analysis.values() for item in values)
    unseen = [
        token
        for token in NUMBER_PATTERN.findall(output)
        if _normalize_number(token) not in allowed
    ]
    if unseen:
        raise ValueError("DeepSeek输出包含上下文中不存在的数字：" + "、".join(unseen[:8]))


def _normalize_number(token: str) -> str:
    text = token.replace(",", "").strip()
    percent = text.endswith("%")
    if percent:
        text = text[:-1]
    try:
        number = float(text)
    except ValueError:
        return token
    normalized = f"{number:.10f}".rstrip("0").rstrip(".")
    return normalized + ("%" if percent else "")


def _safe_message(exc: Exception) -> str:
    text = re.sub(r"\s+", " ", str(exc)).strip()
    text = re.sub(r"(?i)(bearer\s+)[^\s]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*[^\s,;]+", r"\1=[REDACTED]", text)
    return text[:500]
