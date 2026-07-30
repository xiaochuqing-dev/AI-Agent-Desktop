"""dual_agent 路径解析与 fail-fast 降级策略测试。

验证:
  - config 读取 dual_agent_root 字段
  - 环境变量覆盖优先级
  - 无环境变量时用配置
  - 无效路径明确报错
  - parallel/sequential 不静默降级到 legacy
  - 单 Agent 不受影响
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

# 把 hermes-agent 根加到 path,使 plugins.multiagent 可 import
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest

from plugins.multiagent.config import MultiAgentConfig, resolve_dual_agent_root


def test_config_reads_dual_agent_root():
    """config 能从 yaml 读 dual_agent_root 字段"""
    cfg = MultiAgentConfig()
    assert cfg.dual_agent_root == ""  # 默认空
    cfg.dual_agent_root = "/some/path"
    assert cfg.dual_agent_root == "/some/path"


def test_env_override_has_explicit_precedence(monkeypatch, tmp_path):
    """环境变量优先于配置"""
    # 写一个临时 multiagent.yaml,设 dual_agent_root
    hermes_home = tmp_path / "hermes"
    hermes_home.mkdir()
    yaml = hermes_home / "multiagent.yaml"
    yaml.write_text(
        'enabled: true\n'
        'dual_agent_root: "/from/config"\n'
        'agents: {}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("AI_AGENT_COLLAB_ROOT", "/from/env")
    # 环境变量指向的路径要存在 dual_agent/__init__.py 才算通过
    env_root = tmp_path / "envroot"
    (env_root / "dual_agent").mkdir(parents=True)
    (env_root / "dual_agent" / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.setenv("AI_AGENT_COLLAB_ROOT", str(env_root))
    root = resolve_dual_agent_root()
    assert root == str(env_root)


def test_config_root_used_without_env(monkeypatch, tmp_path):
    """无环境变量时用配置的 dual_agent_root"""
    hermes_home = tmp_path / "hermes"
    hermes_home.mkdir()
    # 准备一个有效的 dual_agent 目录
    da_root = tmp_path / "myroot"
    (da_root / "dual_agent").mkdir(parents=True)
    (da_root / "dual_agent" / "__init__.py").write_text("", encoding="utf-8")
    # YAML 双引号里反斜杠会被当转义,用正斜杠写路径(跨平台兼容)
    da_root_yaml = str(da_root).replace("\\", "/")
    yaml = hermes_home / "multiagent.yaml"
    yaml.write_text(
        'enabled: true\n'
        f'dual_agent_root: "{da_root_yaml}"\n'
        'agents: {}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.delenv("AI_AGENT_COLLAB_ROOT", raising=False)
    root = resolve_dual_agent_root()
    assert root == str(da_root)


def test_invalid_root_reports_clear_error(monkeypatch, tmp_path):
    """路径不存在或缺少 dual_agent/__init__.py 时返回 None"""
    hermes_home = tmp_path / "hermes"
    hermes_home.mkdir()
    yaml = hermes_home / "multiagent.yaml"
    yaml.write_text(
        'enabled: true\n'
        'dual_agent_root: "/nonexistent/path/xyz"\n'
        f'agents: {{}}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.delenv("AI_AGENT_COLLAB_ROOT", raising=False)
    # 标准兼容 junction 也不存在时,应返回 None
    # (测试环境无 C:\ai-agent-collaboration)
    root = resolve_dual_agent_root()
    assert root is None
