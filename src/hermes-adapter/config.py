"""Configuration loader for the multi-agent governance plugin.

Reads ``<HERMES_HOME>/multiagent.yaml``.  Falls back to safe defaults so the
plugin never hard-fails the gateway on a missing/malformed config.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class AgentSpec:
    name: str            # hermes | claude | codex
    telegram_username: str = ""
    role: str = ""       # orchestrator | coder


@dataclass
class MultiAgentConfig:
    enabled: bool = True
    agents: Dict[str, AgentSpec] = field(default_factory=dict)
    group_chat_id: str = ""
    at_all_aliases: List[str] = field(default_factory=lambda: ["@all", "@everyone", "@全体"])
    admins: List[str] = field(default_factory=list)
    # HTTP hook receiver
    receiver_host: str = "127.0.0.1"
    receiver_port: int = 8423
    receiver_secret: str = ""
    # scope defaults
    default_scope_type: str = "group"   # group | topic | project
    # dual_agent 核心模块根目录（并行/顺序编排的独立包位置）。
    # 由安装器或 GUI 根据实际安装位置写入；源码不硬编码用户名或 AppData 路径。
    dual_agent_root: str = ""

    def agent_for_username(self, username: str) -> Optional[AgentSpec]:
        """Map a Telegram @username (without leading @) to an AgentSpec."""
        if not username:
            return None
        u = username.lstrip("@").lower()
        for a in self.agents.values():
            if a.telegram_username and a.telegram_username.lstrip("@").lower() == u:
                return a
        return None

    def usernames(self) -> List[str]:
        return [a.telegram_username.lstrip("@") for a in self.agents.values() if a.telegram_username]

    def is_admin(self, user_id: str) -> bool:
        return user_id in self.admins


_DEFAULT_YAML = """\
enabled: true
# Map each bot's Telegram username (without @).  Bot usernames must end in 'bot'.
agents:
  hermes:
    telegram_username: "your_hermes_bot"   # <-- fill with your Hermes bot username
    role: orchestrator
  claude:
    telegram_username: "your_claude_code_bot"
    role: coder
  codex:
    telegram_username: "your_codex_bot"
    role: coder
group_chat_id: "-100xxxxxxxxxx"
at_all_aliases: ["@all", "@everyone", "@全体"]
admins:
  - "REPLACE_WITH_YOUR_USER_ID"
# HTTP hook receiver (binds localhost only; cc-connect posts hook events here)
receiver_host: "127.0.0.1"
receiver_port: 8423
receiver_secret: "CHANGE_ME_TO_A_LONG_RANDOM_SECRET"
default_scope_type: "group"
# dual_agent 核心模块根目录。并行/顺序编排依赖此包。
# 由安装器按实际安装位置写入绝对路径；example 仅占位。
dual_agent_root: "/path/to/ai-agent-collaboration"
"""


def _hermes_home() -> Path:
    home = os.environ.get("HERMES_HOME", "").strip()
    if home:
        return Path(home)
    return Path.home() / ".hermes"


def config_path() -> Path:
    return _hermes_home() / "multiagent.yaml"


def resolve_dual_agent_root() -> Optional[str]:
    """集中解析 dual_agent 根目录，禁止散落多个 sys.path 注入点。

    优先级:
      A. 环境变量 AI_AGENT_COLLAB_ROOT（开发/诊断/临时覆盖）
      B. multiagent.yaml 的 dual_agent_root（正式安装运行主来源）
      C. 受控兼容位置:标准 junction C:\\ai-agent-collaboration（仅 v0.1 兼容）
      D. 全部无效返回 None，由调用方 fail-fast

    返回通过验证的目录绝对路径，或 None。验证:目录存在且含 dual_agent/__init__.py。
    输出诊断日志，不打印 Secret。
    """
    source = ""
    root = ""

    # A. 环境变量（显式覆盖）
    env_val = os.environ.get("AI_AGENT_COLLAB_ROOT", "").strip()
    if env_val:
        source = "env:AI_AGENT_COLLAB_ROOT"
        root = env_val

    # B. 配置文件 dual_agent_root
    if not root:
        try:
            _cfg = load_config()
            if _cfg.dual_agent_root:
                source = "config:multiagent.yaml:dual_agent_root"
                root = _cfg.dual_agent_root
        except Exception:
            logger.exception("multiagent: 读取 dual_agent_root 配置失败")

    # C. 受控兼容位置:标准 junction（仅 v0.1 兼容回退）
    if not root:
        _compat = r"C:\ai-agent-collaboration"
        if Path(_compat).is_dir():
            source = "compat:standard-junction"
            root = _compat

    if not root:
        logger.warning(
            "multiagent: dual_agent 根目录未配置。"
            "请设置 AI_AGENT_COLLAB_ROOT 或在 multiagent.yaml 配置 dual_agent_root。"
            " 并行/顺序任务将不可用。"
        )
        return None

    root_path = Path(root)
    init_file = root_path / "dual_agent" / "__init__.py"
    if not root_path.is_dir():
        logger.error("multiagent: dual_agent 根目录不是有效目录: %s (来源 %s)", root, source)
        return None
    if not init_file.is_file():
        logger.error(
            "multiagent: 路径 %s 下不存在 dual_agent/__init__.py (来源 %s)。"
            " 并行/顺序任务将不可用。", root, source
        )
        return None

    logger.info(
        "multiagent: dual_agent 根目录解析成功: %s (来源 %s, init=%s)",
        root, source, init_file,
    )
    return str(root_path)


def write_default_config() -> Path:
    p = config_path()
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_DEFAULT_YAML, encoding="utf-8")
        logger.info("multiagent: wrote default config to %s", p)
    return p


def load_config() -> MultiAgentConfig:
    """Load config; on any error, return a disabled default so the gateway
    stays healthy.  Emits a loud warning so the operator notices."""
    cfg = MultiAgentConfig()
    p = config_path()
    if not p.exists():
        logger.warning("multiagent: %s not found; plugin disabled. Run with write_default_config().", p)
        cfg.enabled = False
        return cfg
    try:
        # Minimal YAML parser - avoid hard dependency on PyYAML for config that
        # is flat.  If PyYAML is available, prefer it.
        try:
            import yaml  # type: ignore
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except ImportError:
            data = _parse_simple_yaml(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
        cfg.enabled = bool(data.get("enabled", True))
        cfg.group_chat_id = str(data.get("group_chat_id", ""))
        cfg.at_all_aliases = list(data.get("at_all_aliases", cfg.at_all_aliases))
        cfg.admins = [str(x) for x in data.get("admins", [])]
        cfg.receiver_host = str(data.get("receiver_host", "127.0.0.1"))
        cfg.receiver_port = int(data.get("receiver_port", 8423))
        secret = data.get("receiver_secret", "")
        cfg.receiver_secret = str(secret) if secret else ""
        cfg.default_scope_type = str(data.get("default_scope_type", "group"))
        # dual_agent_root: 空值合法（仅禁用并行/顺序，不影响单 Agent）
        cfg.dual_agent_root = str(data.get("dual_agent_root", "") or "").strip()
        agents_raw = data.get("agents", {}) or {}
        for name, spec in agents_raw.items():
            if not isinstance(spec, dict):
                continue
            cfg.agents[name] = AgentSpec(
                name=name,
                telegram_username=str(spec.get("telegram_username", "")),
                role=str(spec.get("role", "")),
            )
        if not cfg.receiver_secret or cfg.receiver_secret == "CHANGE_ME_TO_A_LONG_RANDOM_SECRET":
            logger.warning("multiagent: receiver_secret is unset/default - hook receiver will reject all posts until set.")
        return cfg
    except Exception:
        logger.exception("multiagent: failed to load %s; plugin disabled", p)
        cfg.enabled = False
        return cfg


def _parse_simple_yaml(text: str) -> Dict[str, Any]:
    """Extremely small YAML subset parser for flat key/value + simple lists +
    one-level nested maps.  Only used when PyYAML is unavailable.  Config is
    simple enough that this suffices, but PyYAML is preferred."""
    import re

    result: Dict[str, Any] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        # nested map header  e.g. "agents:"
        m = re.match(r"^([A-Za-z_][\w]*)\s*:\s*$", stripped)
        if m and i + 1 < len(lines) and lines[i + 1].lstrip().startswith("- ") or (
            m and i + 1 < len(lines) and lines[i + 1].startswith("  ")
        ):
            key = m.group(1)
            # could be a list or a nested map
            sub_lines: List[str] = []
            j = i + 1
            while j < len(lines) and (lines[j].startswith("  ") or lines[j].strip() == ""):
                sub_lines.append(lines[j])
                j += 1
            sub_text = "\n".join(sub_lines)
            # detect list
            if any(l.lstrip().startswith("- ") for l in sub_lines):
                items = []
                for l in sub_lines:
                    ls = l.strip()
                    if ls.startswith("- "):
                        val = ls[2:].strip()
                        # strip quotes
                        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                            val = val[1:-1]
                        items.append(val)
                result[key] = items
            else:
                # nested map of maps:  "  name:\n    field: val"
                sub: Dict[str, Any] = {}
                cur_name = None
                cur_fields: Dict[str, str] = {}
                for l in sub_lines:
                    ls = l.strip()
                    if not ls or ls.startswith("#"):
                        continue
                    indent = len(l) - len(l.lstrip())
                    kv = re.match(r"^([A-Za-z_][\w]*)\s*:\s*(.*)$", ls)
                    if kv:
                        if indent <= 2 and not l.startswith("    "):
                            # new sub-entry name
                            if cur_name:
                                sub[cur_name] = cur_fields
                            cur_name = kv.group(1)
                            cur_fields = {}
                            rest = kv.group(2).strip()
                            if rest:
                                cur_fields["_"] = _unquote(rest)
                        else:
                            cur_fields[kv.group(1)] = _unquote(kv.group(2).strip())
                if cur_name:
                    sub[cur_name] = cur_fields
                result[key] = sub
            i = j
            continue
        # simple key: value
        kv = re.match(r"^([A-Za-z_][\w]*)\s*:\s*(.*)$", stripped)
        if kv:
            val = kv.group(2).strip()
            if val == "":
                result[kv.group(1)] = {}
            else:
                result[kv.group(1)] = _unquote(val)
        i += 1
    return result


def _unquote(v: str) -> Any:
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    try:
        return int(v)
    except ValueError:
        return v
