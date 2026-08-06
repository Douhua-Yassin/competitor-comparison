from __future__ import annotations

import json

from app.reporting import analysis_engine


class FakeResponse:
    def __init__(self, content: dict):
        self._content = content

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps(self._content, ensure_ascii=False)},
                }
            ]
        }


def _fallback():
    return {key: ["规则版"] for key in analysis_engine.ANALYSIS_KEYS}


def _settings():
    return {
        "api_key": "test",
        "base_url": "https://example.invalid",
        "model": "deepseek-v4-flash",
        "timeout": 10,
        "max_tokens": 4096,
    }


def test_deepseek_analysis_accepts_only_structured_grounded_numbers(monkeypatch, tmp_path):
    monkeypatch.setattr(analysis_engine, "deepseek_settings", lambda root: _settings())
    content = {key: ["销售额为300，TACOS为10%。"] for key in analysis_engine.ANALYSIS_KEYS}
    captured = {}

    def post(*args, **kwargs):
        captured.update(kwargs)
        return FakeResponse(content)

    result = analysis_engine.generate_analysis(
        {"sales_amount": 300, "tacos": 0.1},
        _fallback(),
        tmp_path,
        post=post,
    )
    assert result.source == "deepseek"
    assert result.warning is None
    assert captured["json"]["model"] == "deepseek-v4-flash"
    assert captured["json"]["thinking"] == {"type": "disabled"}
    assert captured["json"]["response_format"] == {"type": "json_object"}
    assert captured["json"]["max_tokens"] == 4096


def test_deepseek_unseen_number_falls_back_and_records_warning(monkeypatch, tmp_path):
    monkeypatch.setattr(analysis_engine, "deepseek_settings", lambda root: _settings())
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


def test_legacy_deepseek_model_names_are_migrated(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")
    settings = analysis_engine.deepseek_settings(tmp_path)
    assert settings["model"] == "deepseek-v4-flash"
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-reasoner")
    settings = analysis_engine.deepseek_settings(tmp_path)
    assert settings["model"] == "deepseek-v4-pro"
