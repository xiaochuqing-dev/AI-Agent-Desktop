"""Windowless, bounded Hermes CLI capability runner."""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


@dataclass(frozen=True)
class HermesCommandResult:
    returncode: int
    stdout: str
    stderr: str


class HermesCliError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class HermesCliRunner:
    ALLOWED_GATEWAY_ACTIONS = frozenset({"status", "start", "stop", "restart"})

    def __init__(
        self,
        executable: str | Path | None = None,
        *,
        timeout: float = 15.0,
        output_limit: int = 16 * 1024,
    ) -> None:
        self.executable = str(executable) if executable else None
        self.timeout = timeout
        self.output_limit = output_limit

    def resolve_executable(self) -> str:
        candidate = self.executable or shutil.which("hermes") or shutil.which("hermes.exe")
        if not candidate:
            raise HermesCliError("HERMES_NOT_INSTALLED", "没有找到 Hermes CLI。")
        return candidate

    def run(self, *args: str, timeout: float | None = None) -> HermesCommandResult:
        argv = [self.resolve_executable(), *args]
        if any(
            "TELEGRAM_BOT_TOKEN" in arg or ":" in arg and "token" in arg.lower() for arg in args
        ):
            raise HermesCliError(
                "HERMES_SECRET_ARGV_FORBIDDEN", "Hermes Bot Token 不允许通过命令行传递。"
            )
        try:
            completed = subprocess.run(
                argv,
                shell=False,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout if timeout is None else timeout,
                creationflags=_CREATE_NO_WINDOW,
                check=False,
            )
        except FileNotFoundError:
            raise HermesCliError("HERMES_NOT_INSTALLED", "没有找到 Hermes CLI。") from None
        except subprocess.TimeoutExpired:
            raise HermesCliError("HERMES_CLI_TIMEOUT", "Hermes CLI 响应超时。") from None
        stdout = completed.stdout[: self.output_limit]
        stderr = completed.stderr[: self.output_limit]
        return HermesCommandResult(completed.returncode, stdout, stderr)

    def version(self) -> HermesCommandResult:
        return self.run("--version")

    def env_path(self) -> Path:
        result = self.run("config", "env-path")
        if result.returncode != 0:
            raise HermesCliError(
                "HERMES_ENV_PATH_UNAVAILABLE", "无法从 Hermes CLI 获取公开配置路径。"
            )
        raw = result.stdout.strip().splitlines()
        if not raw:
            raise HermesCliError("HERMES_ENV_PATH_UNAVAILABLE", "Hermes CLI 未返回公开配置路径。")
        path = Path(raw[-1].strip().strip('"'))
        if not path.is_absolute():
            path = Path.cwd() / path
        return path

    def gateway(self, action: str) -> HermesCommandResult:
        if action not in self.ALLOWED_GATEWAY_ACTIONS:
            raise HermesCliError(
                "HERMES_GATEWAY_ACTION_UNSUPPORTED", "Hermes Gateway 操作不受支持。"
            )
        return self.run("gateway", action)

    def capabilities(self) -> dict[str, bool | str]:
        result: dict[str, bool | str] = {"installed": False, "env_path": False}
        try:
            version = self.version()
            result["installed"] = version.returncode == 0
            result["version_output"] = version.stdout.strip()[:128]
        except HermesCliError as exc:
            result["diagnostic_code"] = exc.code
            return result
        try:
            self.env_path()
            result["env_path"] = True
        except HermesCliError:
            result["env_path"] = False
        # Probe each action's help surface without executing a mutating action.
        # A command that is present but refuses ``--help`` is reported as
        # unavailable; this keeps capability detection honest across Hermes
        # releases while avoiding an implicit start/stop/restart.
        try:
            help_result = self.run("gateway", "--help")
            help_text = f"{help_result.stdout}\n{help_result.stderr}".lower()
        except HermesCliError:
            help_text = ""
        for action in self.ALLOWED_GATEWAY_ACTIONS:
            result[f"gateway_{action}"] = action in help_text
        return result
