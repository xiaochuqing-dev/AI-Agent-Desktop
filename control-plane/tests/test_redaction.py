from control_plane.security.redaction import contains_secret, redact_value


def test_redact_telegram_bot_token():
    s = "bot token is 123456789:AAEx-abc-def_ghi1234567890123456789 end"
    out = redact_value(s)
    assert "123456789:AAEx" not in out
    assert "<redacted>" in out


def test_redact_openai_key():
    out = redact_value("key=sk-abcdefghijklmnopqrstuvwxyz0123456789")
    assert "sk-abcdefgh" not in out


def test_redact_anthropic_key():
    out = redact_value("sk-ant-abcdefghijklmnopqrstuvwxyz0123456789")
    assert "sk-ant-abcd" not in out


def test_redact_bearer_header():
    out = redact_value("Authorization: Bearer abcdefghijklmnop1234567890")
    assert "abcdefghijkl" not in out


def test_redact_sensitive_field_in_dict():
    data = {"bot_token": "123456789:AAEx_abcdefghij", "name": "ok"}
    out = redact_value(data)
    assert out["bot_token"] == "<redacted>"
    assert out["name"] == "ok"


def test_redact_nested():
    data = {"a": {"api_key": "sk-realsecret0123456789abcdefg", "list": ["sk-realsecret0123456789abcdefg"]}}
    out = redact_value(data)
    assert out["a"]["api_key"] == "<redacted>"
    assert "<redacted>" in out["a"]["list"][0]


def test_contains_secret_detects_token():
    assert contains_secret({"bot_token": "123456789:AAEx_abcdefghijklmnopqrstuv"}) is True


def test_contains_secret_ignores_placeholder():
    assert contains_secret({"bot_token": "<redacted>"}) is False
    assert contains_secret({"name": "plain"}) is False
