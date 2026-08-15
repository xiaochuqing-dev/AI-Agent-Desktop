"""Hermes Gateway lifecycle adapter."""

from __future__ import annotations

from dataclasses import dataclass

from .cli import HermesCliError, HermesCliRunner


@dataclass(frozen=True)
class HermesGatewayStatus:
    state: str
    running: bool
    diagnostic_code: str | None = None
    user_message: str = "Hermes Gateway 状态待确认。"


class HermesGatewayError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class HermesGatewayLifecycle:
    def __init__(self, runner: HermesCliRunner) -> None:
        self.runner = runner

    def status(self) -> HermesGatewayStatus:
        try:
            result = self.runner.gateway("status")
        except HermesCliError as exc:
            return HermesGatewayStatus("unknown", False, exc.code, "无法确认 Hermes Gateway 状态。")
        text = f"{result.stdout}\n{result.stderr}".lower()
        if any(marker in text for marker in ("stopped", "inactive", "not running", "disabled")):
            return HermesGatewayStatus("stopped", False, user_message="Hermes Gateway 已停止。")
        if any(marker in text for marker in ("running", "active", "started", "pid:")):
            return HermesGatewayStatus("running", True, user_message="Hermes Gateway 正在运行。")
        if result.returncode == 0:
            return HermesGatewayStatus("stopped", False, user_message="Hermes Gateway 已停止。")
        return HermesGatewayStatus(
            "unknown", False, "HERMES_GATEWAY_STATUS_UNKNOWN", "无法确认 Hermes Gateway 状态。"
        )

    def run_action(self, action: str) -> HermesGatewayStatus:
        try:
            result = self.runner.gateway(action)
        except HermesCliError as exc:
            raise HermesGatewayError(exc.code, exc.message) from None
        if result.returncode != 0:
            raise HermesGatewayError(
                f"HERMES_GATEWAY_{action.upper()}_FAILED",
                f"Hermes Gateway {action} 操作失败。",
            )
        return self.status()

    def ensure_running(self, *, prior: HermesGatewayStatus | None = None) -> HermesGatewayStatus:
        current = self.status()
        if current.running:
            return current
        try:
            return self.run_action("start")
        except HermesGatewayError:
            if prior is not None and prior.running:
                try:
                    self.run_action("start")
                except HermesGatewayError:
                    pass
            raise

    def restart(self) -> HermesGatewayStatus:
        return self.run_action("restart")

    def restore(self, prior: HermesGatewayStatus) -> HermesGatewayStatus:
        current = self.status()
        if prior.running and not current.running:
            return self.run_action("start")
        if not prior.running and current.running:
            return self.run_action("stop")
        return current
