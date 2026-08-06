from __future__ import annotations

import json

from app.reporting import analysis_engine


class FakeResponse:
    def __init__(self, content: dict):
        self._content = content

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": json.dumps(self._content, ensure_ascii=False)}}]}


def _fallback():
    return {key: ["规则版"] for key in analysis_engine.ANALYSIS_KEYS}


def test_deepseek_analysis_accepts_only_structured_grounded_numbers(monkeypatch, tmp_path):
    monkeypatch.setattr(
        analysis_engine,
        "deepseek_settings",
        lambda root: {"api_key": "test", "base_url": "https://example.invalid", "model": "model", "timeout": 10},
    )
    content = {key: ["销售额为300，TACOS为10%。"] for key in analysis_engine.ANALYSIS_KEYS}
    result = analysis_engine.generate_analysis(
        {"sales_amount": 300, "tacos": 0.1},
        _fallback(),
        tmp_path,
        post=lambda *args, **kwargs: FakeResponse(content),
    )
    assert result.source == "deepseek"
    assert result.warning is None


def test_deepseek_unseen_number_falls_back_and_records_warning(monkeypatch, tmp_path):
    monkeypatch.setattr(
        analysis_engine,
        "deepseek_settings",
        lambda root: {"api_key": "test", "base_url": "https://example.invalid", "model": "model", "timeout": 10},
    )
    content = {key: ["建议把预算提高到9999。"] for key in analysis_engine.ANALYSIS_KEYS}
    result = analysis_engine.generate_analysis(
        {"sales_amount": 300},
        _fallback(),
        tmp_path,
        post=lambda *args, **kwargs: FakeResponse(content),
    )
    assert result.source == "rules_fallback"
    assert result.analysis == _fallback()
    assert "不存在的数字" in (result.warning or "")
