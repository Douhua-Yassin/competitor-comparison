from __future__ import annotations

import pytest

from app.reporting.acceptance_service import _sanitize_text


@pytest.mark.parametrize(
    ("raw", "secret"),
    [
        ("app_id=APP-ID-VALUE", "APP-ID-VALUE"),
        ("app_secret: APP-SECRET-VALUE", "APP-SECRET-VALUE"),
        ("client_secret='CLIENT-SECRET-VALUE'", "CLIENT-SECRET-VALUE"),
        ('api_key="API-KEY-VALUE"', "API-KEY-VALUE"),
        ("access_token=ACCESS-TOKEN-VALUE", "ACCESS-TOKEN-VALUE"),
        ("refresh_token=REFRESH-TOKEN-VALUE", "REFRESH-TOKEN-VALUE"),
        ("id_token=ID-TOKEN-VALUE", "ID-TOKEN-VALUE"),
        ("token=GENERIC-TOKEN-VALUE", "GENERIC-TOKEN-VALUE"),
        ("signature=SIGNATURE-VALUE", "SIGNATURE-VALUE"),
        ("Authorization: Bearer BEARER-TOKEN-VALUE", "BEARER-TOKEN-VALUE"),
        ("Authorization=Basic BASIC-CREDENTIAL-VALUE", "BASIC-CREDENTIAL-VALUE"),
        (
            "https://example.test/path?api_key=QUERY-KEY-VALUE&x=1",
            "QUERY-KEY-VALUE",
        ),
        (
            "https://example.test/path?x=1&refresh_token=QUERY-TOKEN-VALUE",
            "QUERY-TOKEN-VALUE",
        ),
    ],
)
def test_sensitive_value_is_redacted(raw: str, secret: str) -> None:
    sanitized = _sanitize_text(raw)

    assert secret not in sanitized
    assert "***redacted***" in sanitized


def test_non_secret_diagnostic_text_is_preserved() -> None:
    text = "orders 同步失败：429 rate limit"

    assert _sanitize_text(text) == text
