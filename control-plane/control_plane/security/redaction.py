# 安全:脱敏。API 响应、结构化日志、Diagnostic、ReadinessReport 统一过这套规则。
# 默认开启,不可由高级模式绕过。匹配 Telegram bot token、API key、bearer、cookie、
# Authorization header、URL 内凭据、JSON/YAML/TOML/.env 敏感字段。
from __future__ import annotations

import re
from typing import Any

# 敏感字段名(不区分大小写),命中即整体替换
SENSITIVE_FIELD_NAMES = {
    "token",
    "bot_token",
    "api_key",
    "apikey",
    "secret",
    "password",
    "passwd",
    "authorization",
    "auth",
    "bearer",
    "cookie",
    "access_token",
    "refresh_token",
    "client_secret",
    "private_key",
    "session_token",
}

_REDACTED = "<redacted>"

# 凭据形态正则:bot token、OpenAI/Anthropic key、bearer 等。
# Artifact/plan SHA256 是公开完整性信息，必须保留给计划确认与校验。
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b"), _REDACTED),  # Telegram bot token
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), _REDACTED),  # OpenAI 风格 key
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), _REDACTED),  # Anthropic 风格 key
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"), "bearer " + _REDACTED),
    (re.compile(r"(?i)authorization:\s*[A-Za-z0-9._\-]{8,}"), "authorization: " + _REDACTED),
]


def redact_string(value: str) -> str:
    if not isinstance(value, str):
        return value
    out = value
    for pat, repl in _PATTERNS:
        out = pat.sub(repl, out)
    return out


def redact_value(value: Any) -> Any:
    # 递归脱敏 dict/list/str。dict 的敏感字段名整体替换为 <redacted>。
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and k.lower() in SENSITIVE_FIELD_NAMES:
                out[k] = _REDACTED
            else:
                out[k] = redact_value(v)
        return out
    if isinstance(value, list):
        return [redact_value(v) for v in value]
    if isinstance(value, str):
        return redact_string(value)
    return value


def contains_secret(value: Any) -> bool:
    # 扫描命中检测:用于测试与防御性检查。命中返回 True。
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(k, str) and k.lower() in SENSITIVE_FIELD_NAMES:
                # 空字符串或占位符不算命中
                if isinstance(v, str) and v and not v.startswith("<"):
                    return True
            if contains_secret(v):
                return True
        return False
    if isinstance(value, list):
        return any(contains_secret(v) for v in value)
    if isinstance(value, str):
        for pat, _ in _PATTERNS:
            if pat.search(value):
                return True
    return False
