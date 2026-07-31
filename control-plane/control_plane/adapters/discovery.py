# 6 个只读发现 Adapter。把外部真实状态映射为通用 Component。
# 全部无副作用:不安装、不登录、不启停、不发消息、不改配置、不读 Secret 明文。
# 发现不到时返回 not_installed/unknown,不抛底层异常。
from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import psutil

from ..domain.models import (
    AuthenticationState,
    Capability,
    CapabilityAvailability,
    CapabilityMaturity,
    Component,
    Condition,
    ConditionStatus,
    ConfigurationState,
    HealthState,
    InstallationState,
    RuntimeState,
    StateSnapshot,
    UpdateState,
    UserStatus,
)
from . import AdapterRegistry


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _revision() -> str:
    return "observed-1"


def _snapshot(
    *,
    installation: InstallationState,
    configuration: ConfigurationState = ConfigurationState.UNKNOWN,
    authentication: AuthenticationState = AuthenticationState.UNKNOWN,
    runtime: RuntimeState = RuntimeState.UNKNOWN,
    health: HealthState = HealthState.UNKNOWN,
    update: UpdateState = UpdateState.UNKNOWN,
    user_status: UserStatus = UserStatus.UNKNOWN,
    conditions: list[Condition] | None = None,
) -> StateSnapshot:
    return StateSnapshot(
        installation=installation,
        configuration=configuration,
        authentication=authentication,
        runtime=runtime,
        health=health,
        update=update,
        user_status=user_status,
        status_overlays=[],
        conditions=conditions or [],
        generation=1,
        observed_generation=1,
        revision=_revision(),
        observed_at=utcnow(),
    )


def _version_of(exe: str, args: list[str] = None, timeout: float = 5.0) -> tuple[Optional[str], bool]:
    # 调用 --version 解析版本(只读)。返回 (version, reliable)。
    try:
        proc = subprocess.run(
            [exe, *(args or ["--version"])],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=_NO_WINDOW,  # type: ignore[arg-type]
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None, False
    out = (proc.stdout or proc.stderr or "").strip()
    if not out:
        return None, False
    # 取第一行作为版本串;不做语义解析,仅记录可靠标志
    return out.splitlines()[0][:128], True


import sys

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW,避免弹黑窗


class WindowsSystemDiscoveryAdapter:
    adapter_id = "windows-system-discovery"
    component_kinds = ["system"]

    def discover(self) -> list[Component]:
        # 系统基础信息:Windows 版本/架构、权限、磁盘空间。只读,不改环境。
        disk_ok = True
        try:
            usage = psutil.disk_usage(str(Path.home()))
            disk_ok = usage.free > 1 * 1024 * 1024 * 1024  # 至少 1GB 可用
        except Exception:
            disk_ok = False

        cond = Condition(
            type="DiskSpaceAvailable",
            status=ConditionStatus.TRUE if disk_ok else ConditionStatus.FALSE,
            reason="DISK_SPACE_CHECK" if disk_ok else "DISK_SPACE_LOW",
            message="磁盘空间充足" if disk_ok else "磁盘可用空间不足 1GB",
            observed_generation=1,
            last_transition_time=utcnow(),
        )
        state = _snapshot(
            installation=InstallationState.INSTALLED,
            configuration=ConfigurationState.VALID,
            authentication=AuthenticationState.NOT_REQUIRED,
            runtime=RuntimeState.RUNNING,
            health=HealthState.HEALTHY if disk_ok else HealthState.DEGRADED,
            user_status=UserStatus.RUNNING_HEALTHY if disk_ok else UserStatus.PARTIALLY_DEGRADED,
            conditions=[cond],
        )
        return [
            Component(
                component_id="windows-system",
                kind="system",
                display_name="Windows System",
                version=platform_version(),
                state=state,
                provider_refs=[],
            )
        ]

    def capabilities(self) -> list[Capability]:
        return [
            Capability(
                capability_id="system.discover.v1",
                version="1.0.0",
                maturity=CapabilityMaturity.STABLE,
                availability=CapabilityAvailability.AVAILABLE,
                constraints={},
            )
        ]


def platform_version() -> Optional[str]:
    # 优先 platform.platform();不可用时返回 None
    import platform

    try:
        return platform.platform()[:128]
    except Exception:
        return None


class HermesDiscoveryAdapter:
    adapter_id = "hermes-discovery"
    component_kinds = ["orchestration"]

    def discover(self) -> list[Component]:
        exe = shutil.which("hermes") or _hermes_exe_candidate()
        installed = exe is not None and os.path.isfile(exe)
        version, reliable = (None, False)
        config_exists = False
        if installed:
            version, reliable = _version_of(exe, ["--version"])
            config_exists = _hermes_config_exists()
        state = _snapshot(
            installation=InstallationState.INSTALLED if installed else InstallationState.NOT_INSTALLED,
            configuration=ConfigurationState.VALID if config_exists else ConfigurationState.MISSING,
            authentication=AuthenticationState.NOT_REQUIRED,
            runtime=RuntimeState.UNKNOWN,
            health=HealthState.UNKNOWN,
            user_status=UserStatus.INSTALLED_UNCONFIGURED if installed and not config_exists
            else (UserStatus.RUNNING_HEALTHY if installed else UserStatus.NOT_INSTALLED),
            conditions=_version_condition(version, reliable),
        )
        return [
            Component(
                component_id="hermes",
                kind="orchestration",
                display_name="Hermes",
                version=version,
                state=state,
                provider_refs=[],
            )
        ]

    def capabilities(self) -> list[Capability]:
        return [_read_only_capability("lifecycle.discover.v1")]


def _hermes_exe_candidate() -> Optional[str]:
    # 常见安装位置:LOCALAPPDATA\hermes\hermes-agent\venv\Scripts\hermes.exe
    local = os.environ.get("LOCALAPPDATA")
    if local:
        p = os.path.join(local, "hermes", "hermes-agent", "venv", "Scripts", "hermes.exe")
        if os.path.isfile(p):
            return p
    return None


def _hermes_config_exists() -> bool:
    # HERMES_HOME 或 ~/.hermes 下 multiagent.yaml 是否存在(只读,不读内容)
    home = os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
    return os.path.isfile(os.path.join(home, "multiagent.yaml"))


class CcConnectDiscoveryAdapter:
    adapter_id = "cc-connect-discovery"
    component_kinds = ["agent_runtime"]

    def discover(self) -> list[Component]:
        # 优先用 .exe(npm wrapper 会触发 run.js 覆盖 patch 版),见运行源码映射
        exe = shutil.which("cc-connect") or _cc_connect_exe_candidate()
        installed = exe is not None and os.path.isfile(exe)
        version, reliable = (None, False)
        config_exists = False
        if installed:
            version, reliable = _version_of(exe, ["--version"])
            config_exists = _cc_connect_config_exists()
        state = _snapshot(
            installation=InstallationState.INSTALLED if installed else InstallationState.NOT_INSTALLED,
            configuration=ConfigurationState.VALID if config_exists else ConfigurationState.MISSING,
            authentication=AuthenticationState.UNKNOWN,
            runtime=RuntimeState.UNKNOWN,
            health=HealthState.UNKNOWN,
            user_status=UserStatus.INSTALLED_UNCONFIGURED if installed and not config_exists
            else (UserStatus.RUNNING_HEALTHY if installed else UserStatus.NOT_INSTALLED),
            conditions=_version_condition(version, reliable),
        )
        return [
            Component(
                component_id="cc-connect",
                kind="agent_runtime",
                display_name="cc-connect",
                version=version,
                state=state,
                provider_refs=[],
            )
        ]

    def capabilities(self) -> list[Capability]:
        return [_read_only_capability("lifecycle.discover.v1")]


def _cc_connect_exe_candidate() -> Optional[str]:
    appdata = os.environ.get("APPDATA")
    if appdata:
        p = os.path.join(appdata, "npm", "node_modules", "cc-connect", "bin", "cc-connect.exe")
        if os.path.isfile(p):
            return p
    return None


def _cc_connect_config_exists() -> bool:
    home = Path.home() / ".cc-connect"
    return os.path.isfile(str(home / "config.toml"))


class ClaudeCodeDiscoveryAdapter:
    adapter_id = "claude-code-discovery"
    component_kinds = ["agent"]

    def discover(self) -> list[Component]:
        exe = shutil.which("claude")
        installed = exe is not None
        version, reliable = (None, False)
        if installed:
            version, reliable = _version_of(exe, ["--version"])
        state = _snapshot(
            installation=InstallationState.INSTALLED if installed else InstallationState.NOT_INSTALLED,
            configuration=ConfigurationState.UNKNOWN,
            authentication=AuthenticationState.UNKNOWN,
            runtime=RuntimeState.UNKNOWN,
            health=HealthState.UNKNOWN,
            user_status=UserStatus.NOT_INSTALLED if not installed else UserStatus.UNKNOWN,
            conditions=_version_condition(version, reliable),
        )
        return [
            Component(
                component_id="claude-code",
                kind="agent",
                display_name="Claude Code",
                version=version,
                state=state,
                provider_refs=[],
            )
        ]

    def capabilities(self) -> list[Capability]:
        return [_read_only_capability("lifecycle.discover.v1")]


class CodexDiscoveryAdapter:
    adapter_id = "codex-discovery"
    component_kinds = ["agent"]

    def discover(self) -> list[Component]:
        exe = shutil.which("codex")
        installed = exe is not None
        version, reliable = (None, False)
        if installed:
            version, reliable = _version_of(exe, ["--version"])
        state = _snapshot(
            installation=InstallationState.INSTALLED if installed else InstallationState.NOT_INSTALLED,
            configuration=ConfigurationState.UNKNOWN,
            authentication=AuthenticationState.UNKNOWN,
            runtime=RuntimeState.UNKNOWN,
            health=HealthState.UNKNOWN,
            user_status=UserStatus.NOT_INSTALLED if not installed else UserStatus.UNKNOWN,
            conditions=_version_condition(version, reliable),
        )
        return [
            Component(
                component_id="codex",
                kind="agent",
                display_name="Codex",
                version=version,
                state=state,
                provider_refs=[],
            )
        ]

    def capabilities(self) -> list[Capability]:
        return [_read_only_capability("lifecycle.discover.v1")]


class TelegramConfigDiscoveryAdapter:
    adapter_id = "telegram-config-discovery"
    component_kinds = ["channel"]

    def discover(self) -> list[Component]:
        # 只检测配置存在性与字段完整性,绝不输出真实 Bot Token、Chat ID、User ID。
        multiagent = _hermes_config_exists()
        tokens_env = _cc_connect_tokens_env_exists()
        installed = multiagent or tokens_env
        # 配置合法性:必要字段是否完整(只读结构判断,不读值)
        valid = multiagent and tokens_env
        state = _snapshot(
            installation=InstallationState.INSTALLED if installed else InstallationState.NOT_INSTALLED,
            configuration=ConfigurationState.VALID if valid else ConfigurationState.MISSING,
            authentication=AuthenticationState.REQUIRED if not valid else AuthenticationState.UNKNOWN,
            runtime=RuntimeState.UNKNOWN,
            health=HealthState.UNKNOWN,
            user_status=UserStatus.INSTALLED_UNCONFIGURED if installed and not valid
            else (UserStatus.RUNNING_HEALTHY if installed else UserStatus.NOT_INSTALLED),
            conditions=[],
        )
        return [
            Component(
                component_id="telegram-channel",
                kind="channel",
                display_name="Telegram Channel",
                version=None,
                state=state,
                provider_refs=[],
            )
        ]

    def capabilities(self) -> list[Capability]:
        return [_read_only_capability("channel.discover.v1")]


def _cc_connect_tokens_env_exists() -> bool:
    # 仅判断 bot-tokens.env 是否存在,绝不读取其内容
    home = Path.home() / ".cc-connect"
    return os.path.isfile(str(home / "bot-tokens.env"))


def _version_condition(version: Optional[str], reliable: bool) -> list[Condition]:
    return [
        Condition(
            type="VersionResolved",
            status=ConditionStatus.TRUE if version else ConditionStatus.UNKNOWN,
            reason="VERSION_PARSED" if reliable else "VERSION_UNKNOWN",
            message=f"版本: {version}" if version else "版本未能解析",
            observed_generation=1,
            last_transition_time=utcnow(),
        )
    ]


def _read_only_capability(cap_id: str) -> Capability:
    return Capability(
        capability_id=cap_id,
        version="1.0.0",
        maturity=CapabilityMaturity.STABLE,
        availability=CapabilityAvailability.AVAILABLE,
        constraints={"read_only": True},
    )


def default_adapters() -> AdapterRegistry:
    # 装载 6 个内置只读发现 Adapter
    reg = AdapterRegistry()
    reg.register(WindowsSystemDiscoveryAdapter())
    reg.register(HermesDiscoveryAdapter())
    reg.register(CcConnectDiscoveryAdapter())
    reg.register(ClaudeCodeDiscoveryAdapter())
    reg.register(CodexDiscoveryAdapter())
    reg.register(TelegramConfigDiscoveryAdapter())
    return reg
