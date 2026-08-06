from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

SENSITIVE_PARTS = ("secret", "token", "password", "authorization", "signature", "app_id")


def to_plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return to_plain(value.value)
    if is_dataclass(value):
        return to_plain(asdict(value))
    if hasattr(value, "model_dump"):
        try:
            return to_plain(value.model_dump(mode="json"))
        except TypeError:
            return to_plain(value.model_dump())
    if hasattr(value, "dict") and callable(value.dict):
        return to_plain(value.dict())
    if isinstance(value, dict):
        return {str(k): to_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_plain(item) for item in value]
    if hasattr(value, "__dict__"):
        return to_plain(vars(value))
    return repr(value)


def redact(value: Any, key: str = "") -> Any:
    lowered = key.lower()
    if any(part in lowered for part in SENSITIVE_PARTS):
        return "***redacted***"
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def extract_records(payload: Any) -> list[Any]:
    plain = to_plain(payload)
    if isinstance(plain, list):
        return plain
    if not isinstance(plain, dict):
        return []
    preferred = ("records", "items", "list", "lists", "rows", "row_data", "results")
    for key in preferred:
        value = plain.get(key)
        if isinstance(value, list):
            return value
    data = plain.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in preferred:
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def extract_fields(payload: Any, limit: int = 10) -> list[str]:
    records = extract_records(payload)[:limit]
    fields: set[str] = set()
    for item in records:
        if isinstance(item, dict):
            fields.update(str(key) for key in item.keys())
    if fields:
        return sorted(fields)
    plain = to_plain(payload)
    return sorted(str(key) for key in plain.keys()) if isinstance(plain, dict) else []
