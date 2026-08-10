from scripts.validate_gui_candidate import _scan_sensitive


def test_candidate_validator_scans_text_for_telegram_tokens() -> None:
    findings: list[str] = []
    _scan_sensitive(
        "text",
        b"123456789:AAAbbb1234567890_cccDDDxxxyyy111222333444555",
        findings,
    )
    assert findings == ["text:telegram-bot-token"]


def test_candidate_validator_ignores_binary_lookup_table_false_positive() -> None:
    findings: list[str] = []
    _scan_sensitive(
        "binary",
        b"\x00\x01 456789:CDEFGHIJSTUVWXYZcdefghijstuvwxyz \xff",
        findings,
        binary=True,
    )
    assert findings == []
