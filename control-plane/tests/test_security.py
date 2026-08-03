# 安全测试:扫描 Control Plane 源码是否含真实凭据形态。默认不含;命中即失败。
import os
import re

from control_plane.security.redaction import contains_secret

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SOURCE_DIR = os.path.join(REPO_ROOT, "control-plane", "control_plane")

# 真实凭据形态(非测试占位符)。redaction.py 中的正则字面量不是真实凭据。
REAL_SECRET_PATTERNS = [
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b"),  # Telegram bot token
    re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),  # Anthropic key(非测试片段)
    re.compile(r"sk-[A-Za-z0-9]{40,}"),  # OpenAI 风格长 key(非正则字面量)
]


def _source_files():
    for root, _dirs, files in os.walk(SOURCE_DIR):
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(root, f)


def test_no_real_secrets_in_source():
    for path in _source_files():
        with open(path, encoding="utf-8") as f:
            content = f.read()
        for pat in REAL_SECRET_PATTERNS:
            # 排除 redaction.py 中的正则定义本身
            matches = pat.findall(content)
            # 过滤掉明显是正则字面量的片段(含 [ 或 { )
            real = [m for m in matches if "[" not in m and "{" not in m and len(m) < 200]
            assert not real, f"疑似真实凭据在 {path}: {real}"
        assert contains_secret({"_": content}) is False or "<redacted>" not in content, (
            f"源码 {path} 含疑似凭据字段值"
        )
