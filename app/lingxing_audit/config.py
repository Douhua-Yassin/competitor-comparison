from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASE_URL = "https://openapi.lingxing.com"


class AuditConfigurationError(RuntimeError):
    """Raised when Lingxing audit configuration is absent or unsafe."""


@dataclass(frozen=True)
class AuditSettings:
    app_id: str
    app_secret: str
    base_url: str
    output_dir: Path
    lookback_days: int = 7
    sid: int | None = None
    timeout_seconds: int = 60

    @classmethod
    def load(cls, env_path: Path | None = None) -> "AuditSettings":
        path = env_path or ROOT / ".env"
        file_values = dotenv_values(path) if path.exists() else {}

        def read(name: str, default: str = "") -> str:
            return str(os.getenv(name) or file_values.get(name) or default).strip()

        app_id = read("LINGXING_APP_ID")
        app_secret = read("LINGXING_APP_SECRET")
        base_url = read("LINGXING_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
        if not app_id or not app_secret:
            raise AuditConfigurationError(
                "缺少 LINGXING_APP_ID 或 LINGXING_APP_SECRET，请检查项目根目录 .env。"
            )
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise AuditConfigurationError("LINGXING_BASE_URL 必须是有效的 HTTPS 地址。")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise AuditConfigurationError(
                "LINGXING_BASE_URL 不得包含账号、密码、查询参数或片段。"
            )

        lookback_days = _positive_int(read("LINGXING_AUDIT_LOOKBACK_DAYS", "7"), 7)
        timeout_seconds = _positive_int(read("LINGXING_AUDIT_TIMEOUT_SECONDS", "60"), 60)
        sid_text = read("LINGXING_SID")
        sid = int(sid_text) if sid_text.isdigit() else None
        output_dir_text = read("LINGXING_AUDIT_OUTPUT_DIR")
        output_dir = Path(output_dir_text) if output_dir_text else ROOT / "data" / "lingxing_audit"
        if not output_dir.is_absolute():
            output_dir = ROOT / output_dir
        return cls(
            app_id=app_id,
            app_secret=app_secret,
            base_url=base_url,
            output_dir=output_dir,
            lookback_days=lookback_days,
            sid=sid,
            timeout_seconds=timeout_seconds,
        )

    def public_summary(self) -> dict[str, object]:
        return {
            "app_id": _mask(self.app_id),
            "app_secret": "***configured***",
            "base_url": self.base_url,
            "lookback_days": self.lookback_days,
            "sid": self.sid,
            "timeout_seconds": self.timeout_seconds,
            "output_dir": str(self.output_dir),
        }


def _positive_int(value: str, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _mask(value: str) -> str:
    if len(value) <= 6:
        return "***"
    return f"{value[:3]}***{value[-3:]}"
