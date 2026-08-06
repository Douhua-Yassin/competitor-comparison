from pathlib import Path

from app.reporting.sync_acceptance import build_sync_acceptance, write_acceptance_report


def test_no_sync_returns_safe_state(tmp_path):
    payload = build_sync_acceptance(tmp_path / "empty.db", generated_at="2026-08-06T00:00:00")

    assert payload["state"] == "no_sync"
    assert payload["latest_run"] is None


def test_export_rejects_unknown_format(tmp_path):
    try:
        write_acceptance_report("xml", db_path=tmp_path / "db.sqlite", output_dir=tmp_path)
    except ValueError as exc:
        assert "md" in str(exc)
    else:
        raise AssertionError("unknown format should fail")


def test_sensitive_warning_is_not_exported(tmp_path):
    payload = build_sync_acceptance(tmp_path / "empty.db")
    text = str(payload)

    assert "access_token=" not in text
    assert "Bearer " not in text
