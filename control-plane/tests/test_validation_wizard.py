from __future__ import annotations

import json
from types import SimpleNamespace

from control_plane.security.redaction import contains_secret
from control_plane.validation.wizard import (
    cleanup_validation_data,
    export_redacted_report,
    run_headless_checks,
)
from scripts import candidate_entry


def test_windowed_candidate_provides_standard_streams(monkeypatch):
    fake_sys = SimpleNamespace(stdout=None, stderr=None)
    monkeypatch.setattr(candidate_entry, "sys", fake_sys)

    candidate_entry.ensure_standard_streams()

    try:
        assert fake_sys.stdout is not None
        assert fake_sys.stderr is not None
    finally:
        fake_sys.stdout.close()
        fake_sys.stderr.close()


def test_headless_candidate_report_is_safe_and_cleanup_is_scoped(tmp_path):
    root = tmp_path / "候选包 (x)"
    root.mkdir()
    report = run_headless_checks(root)
    assert report["candidate_version"] == "0.1.0-stage-a"
    assert report["components"]["chrome_agent"] is False
    assert report["telegram_messages_sent"] == 0
    assert report["secret_values_recorded"] == 0
    assert report["message_bodies_recorded"] == 0
    assert not contains_secret(report)

    report_path = export_redacted_report(
        {**report, "token": "123456:ThisIsASecretTokenThatMustBeRedacted"},
        root / "reports" / "user-validation-redacted.json",
    )
    exported = json.loads(report_path.read_text(encoding="utf-8"))
    assert exported["token"] == "<redacted>"
    assert exported["redaction_applied"] is True

    (root / "validation-data").mkdir()
    (root / "validation-data" / "control_plane.db").write_text("synthetic", encoding="utf-8")
    removed = cleanup_validation_data(root)
    assert len(removed) == 2
    assert not (root / "validation-data").exists()
    assert not report_path.exists()
