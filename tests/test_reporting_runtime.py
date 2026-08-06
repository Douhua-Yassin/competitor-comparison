from __future__ import annotations

import pytest

pytest.importorskip("docx")

from fastapi.testclient import TestClient

from app.reporting_app import app


def test_reporting_page_disables_cache_and_runtime_guard_is_available():
    with TestClient(app) as client:
        page = client.get("/reporting")
        assert page.status_code == 200
        assert "no-store" in page.headers["cache-control"]
        assert page.headers["x-reporting-service"] == "local-8790"
        assert "/static/reporting-runtime-guard.js" in page.text

        guard = client.get("/static/reporting-runtime-guard.js")
        assert guard.status_code == 200
        assert "no-store" in guard.headers["cache-control"]
        assert "本机8790接口响应超时" in guard.text


def test_diagnostics_reports_state_without_exposing_credentials(monkeypatch):
    app_id = "APP-ID-MUST-NOT-LEAK"
    secret = "APP-SECRET-MUST-NOT-LEAK"
    monkeypatch.setenv("LINGXING_APP_ID", app_id)
    monkeypatch.setenv("LINGXING_APP_SECRET", secret)
    monkeypatch.setenv("LINGXING_BASE_URL", "https://openapi.lingxing.com")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")

    with TestClient(app) as client:
        response = client.get("/api/reporting/diagnostics")

    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "reporting"
    assert data["database"]["readable"] is True
    assert data["lingxing"]["configured"] is True
    assert data["proxy"]["loopback_bypassed"] is True
    assert data["browser"]["launch_mode"] == "isolated-direct"
    serialized = response.text
    assert app_id not in serialized
    assert secret not in serialized
