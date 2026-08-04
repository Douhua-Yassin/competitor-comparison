from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from app.lingxing_audit.config import AuditSettings
from app.lingxing_audit.models import ProbeDefinition
from app.lingxing_audit.runner import AuditRunner
from app.lingxing_audit.serializer import extract_fields, extract_records, redact


class FakeApi:
    def __init__(self, **_: object) -> None:
        self.basic = SimpleNamespace(Sellers=self.Sellers)
        self.ads = SimpleNamespace(AdProfiles=self.AdProfiles)
        self.sales = SimpleNamespace(Orders=self.Orders)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def AccessToken(self):
        return {"access_token": "sensitive-token", "expires_in": 3600}

    async def Sellers(self):
        return {"data": [{"sid": 123, "seller_name": "US Store"}]}

    async def AdProfiles(self):
        return {"data": [{"profile_id": 456, "country": "US"}]}

    async def Orders(
        self,
        sid: int,
        start_date: str,
        end_date: str,
        offset: int = 0,
        length: int = 20,
    ):
        assert sid == 123
        assert start_date <= end_date
        return {"data": {"records": [{"amazon_order_id": "A1", "sales": 12.5}]}}


def test_runner_discovers_context_and_writes_reports(tmp_path: Path) -> None:
    settings = AuditSettings(
        app_id="abcdefghijklmnop",
        app_secret="secret",
        base_url="https://openapi.lingxing.com",
        output_dir=tmp_path,
    )
    probes = (
        ProbeDefinition("token", "认证", "令牌", "AccessToken", ""),
        ProbeDefinition("sellers", "基础", "店铺", "basic.Sellers", ""),
        ProbeDefinition("ad_profiles", "广告", "账户", "ads.AdProfiles", ""),
        ProbeDefinition(
            "orders",
            "销售",
            "订单",
            "sales.Orders",
            "",
            {"offset": 0, "length": 20},
        ),
    )
    report = asyncio.run(AuditRunner(settings, api_factory=FakeApi, probes=probes).run())
    assert report.summary == {"success": 4}
    assert report.context == {"sid": 123, "profile_id": 456}
    run_dir = tmp_path / report.run_id
    assert (run_dir / "audit-report.json").exists()
    assert (run_dir / "audit-report.md").exists()
    saved = json.loads((run_dir / "samples" / "token.json").read_text(encoding="utf-8"))
    assert saved["access_token"] == "***redacted***"


def test_serializer_extracts_nested_records_and_fields() -> None:
    payload = {
        "data": {
            "records": [
                {"asin": "A", "sales": 1},
                {"asin": "B", "sales": 2},
            ]
        }
    }
    assert len(extract_records(payload)) == 2
    assert extract_fields(payload) == ["asin", "sales"]


def test_redact_removes_credentials() -> None:
    value = redact({"app_secret": "x", "access_token": "y", "data": 1})
    assert value == {
        "app_secret": "***redacted***",
        "access_token": "***redacted***",
        "data": 1,
    }
