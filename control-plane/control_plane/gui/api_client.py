from __future__ import annotations

import json
import os
import secrets
import sys
import time
from abc import ABC, abstractmethod
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

SLOTS = ("hermes", "claude", "codex")
DISPLAY_NAMES = {"hermes": "Hermes", "claude": "Claude Code", "codex": "Codex"}


class GuiApiError(RuntimeError):
    def __init__(self, message: str, *, code: str = "GUI_API_ERROR") -> None:
        self.code = code
        super().__init__(message)


class GuiApiClient(ABC):
    @abstractmethod
    def snapshot(self) -> dict[str, Any]: ...

    @abstractmethod
    def save_and_verify_tokens(self, tokens: dict[str, str]) -> dict[str, Any]: ...

    @abstractmethod
    def begin_binding(self) -> dict[str, Any]: ...

    @abstractmethod
    def resume_binding(self, session_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def poll_binding(self) -> dict[str, Any]: ...

    @abstractmethod
    def complete_configuration(self) -> dict[str, Any]: ...

    @abstractmethod
    def diagnostics(self) -> list[dict[str, Any]]: ...

    def dashboard_snapshot(self) -> dict[str, Any]:
        """Return the dashboard read model without changing Control Plane state."""
        return self.snapshot()

    def refresh_snapshot(self) -> dict[str, Any]:
        """Run read-only probes, including an explicit Agent detection refresh."""
        return self.snapshot()

    def live_links(self) -> list[dict[str, Any]]:
        return []

    def run_live_test(self, *, confirmation: bool) -> list[dict[str, Any]]:
        if not confirmation:
            raise GuiApiError("发送真实测试消息前需要明确确认。", code="E2E_CONFIRMATION_REQUIRED")
        raise GuiApiError("当前客户端不支持真实聊天验证。", code="E2E_UNAVAILABLE")

    def open_cc_switch(self) -> dict[str, Any]:
        raise GuiApiError("没有检测到可打开的 CC Switch。", code="CC_SWITCH_NOT_INSTALLED")


class HttpControlPlaneClient(GuiApiClient):
    """Small synchronous client used from the GUI worker thread.

    The bearer token is only sent in the Authorization header.  Secrets are
    accepted by save_and_verify_tokens and never retained on the client.
    """

    def __init__(
        self,
        base_url: str,
        bearer_token: str,
        *,
        timeout: float = 15.0,
        data_dir: Path | None = None,
        artifact_dir: Path | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = {"Authorization": f"Bearer {bearer_token}"}
        self.binding: dict[str, Any] | None = None
        self.data_dir = data_dir
        self.artifact_dir = artifact_dir

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        merged = dict(self.headers)
        if headers:
            merged.update(headers)
        try:
            response = httpx.request(
                method,
                f"{self.base_url}{path}",
                headers=merged,
                json=json_body,
                timeout=self.timeout,
                follow_redirects=False,
                trust_env=False,
            )
        except httpx.HTTPError as exc:
            raise GuiApiError(
                "无法连接本机 Control Plane，请稍后重试。", code="CONTROL_PLANE_UNAVAILABLE"
            ) from exc
        if response.status_code >= 400:
            try:
                problem = response.json()
            except ValueError:
                problem = {}
            message = problem.get("user_message") or problem.get("detail") or "本机服务返回了错误。"
            code = problem.get("code") or "CONTROL_PLANE_REQUEST_FAILED"
            raise GuiApiError(str(message), code=str(code))
        return response

    @staticmethod
    def _key(prefix: str) -> str:
        return f"gui-{prefix}-{secrets.token_hex(12)}"

    def _wait_operation(self, operation_id: str, *, timeout: float = 30.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            operation = self._request("GET", f"/api/v1/operations/{operation_id}").json()
            if operation.get("status") == "succeeded":
                return operation
            if operation.get("status") in {"failed", "canceled"}:
                error = operation.get("error") or {}
                raise GuiApiError(
                    str(error.get("message") or "操作没有完成。"),
                    code=str(error.get("code") or "OPERATION_FAILED"),
                )
            time.sleep(0.08)
        raise GuiApiError("操作等待超时，请点击刷新后重试。", code="OPERATION_TIMEOUT")

    def snapshot(self) -> dict[str, Any]:
        snapshot = self._request("GET", "/api/v1/onboarding/snapshot").json()
        self._last_snapshot = snapshot
        return snapshot

    def refresh_snapshot(self) -> dict[str, Any]:
        snapshot = self._request("GET", "/api/v1/onboarding/snapshot?refresh_agents=true").json()
        self._last_snapshot = snapshot
        return snapshot

    def dashboard_snapshot(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/dashboard/snapshot").json()

    def save_and_verify_tokens(self, tokens: dict[str, str]) -> dict[str, Any]:
        for slot in SLOTS:
            token = tokens.get(slot, "").strip()
            if not token:
                raise GuiApiError(f"请填写 {DISPLAY_NAMES[slot]} Bot Token。", code="TOKEN_EMPTY")
            key = self._key(f"credential-{slot}")
            try:
                self._request(
                    "PUT",
                    f"/api/v1/credentials/telegram/{slot}",
                    json_body={"secret": token},
                    headers={"Idempotency-Key": key},
                )
            except GuiApiError as exc:
                if exc.code not in {"CREDENTIAL_ALREADY_EXISTS", "CONTROL_PLANE_REQUEST_FAILED"}:
                    raise
                self._request(
                    "POST",
                    f"/api/v1/credentials/telegram/{slot}:replace",
                    json_body={"secret": token},
                    headers={"Idempotency-Key": self._key(f"replace-{slot}")},
                )
            operation = self._request(
                "POST",
                f"/api/v1/telegram/bots/{slot}:verify",
                json_body={},
                headers={"Idempotency-Key": self._key(f"verify-{slot}")},
            ).json()
            self._wait_operation(operation["operation_id"])
        return self.snapshot()

    def begin_binding(self) -> dict[str, Any]:
        self.binding = self._request(
            "POST",
            "/api/v1/telegram/bindings",
            json_body={"expires_in_seconds": 900, "runtimes_stopped_confirmation": True},
        ).json()
        return deepcopy(self.binding)

    def resume_binding(self, session_id: str) -> dict[str, Any]:
        self.binding = self._request(
            "POST",
            f"/api/v1/telegram/bindings/{session_id}:resume",
            json_body={"expires_in_seconds": 900, "runtimes_stopped_confirmation": True},
        ).json()
        return deepcopy(self.binding)

    def poll_binding(self) -> dict[str, Any]:
        if self.binding is None:
            self.begin_binding()
        assert self.binding is not None
        session_id = self.binding["session_id"]
        for slot in SLOTS:
            operation = self._request(
                "POST",
                f"/api/v1/telegram/bindings/{session_id}/slots/{slot}:poll",
                json_body={"timeout_seconds": 0},
                headers={"Idempotency-Key": self._key(f"poll-{slot}")},
            ).json()
            self._wait_operation(operation["operation_id"], timeout=10)
        state = self._request("GET", f"/api/v1/telegram/bindings/{session_id}").json()
        self.binding.update(state)
        return deepcopy(self.binding)

    def complete_configuration(self) -> dict[str, Any]:
        binding_session_id = (self.binding or {}).get("session_id")
        if not binding_session_id:
            latest = getattr(self, "_last_snapshot", None) or self.snapshot()
            binding_session_id = (latest.get("binding") or {}).get("session_id")
        if not binding_session_id:
            raise GuiApiError(
                "请先完成 Telegram 私聊和群聊绑定。", code="TELEGRAM_BINDING_NOT_COMPLETE"
            )
        self._ensure_cc_connect_installed()
        self._ensure_product_ownership()
        self._ensure_native_configuration(str(binding_session_id))
        detections = self.refresh_snapshot().get("agents", [])
        missing = [
            item.get("display_name", item.get("slot", "Agent"))
            for item in detections
            if not item.get("acceptable")
        ]
        if missing:
            raise GuiApiError(
                "请先安装或修复这些 Agent：" + "、".join(str(item) for item in missing),
                code="AGENT_NOT_READY",
            )
        self._ensure_runtime_ready()
        snapshot = self.snapshot()
        if not snapshot.get("onboarding_complete"):
            raise GuiApiError(
                "基础配置尚未通过全部真实性检查，请查看详细诊断。",
                code="ONBOARDING_NOT_READY",
            )
        return snapshot

    def _ensure_runtime_ready(self) -> None:
        native = self._request("GET", "/api/v1/components/cc-connect/native-configuration").json()
        revision = int(native.get("revision") or 0)
        if native.get("status") != "valid" or revision < 1:
            raise GuiApiError("连接配置尚未有效。", code="CC_CONNECT_CONFIGURATION_NOT_READY")
        current = self._request("GET", "/api/v1/components/cc-connect/lifecycle").json()
        if not self._runtime_ready(current, revision):
            action = "restart" if current.get("observed_state") == "running_partial" else "start"
            operation = self._request(
                "POST",
                f"/api/v1/components/cc-connect:{action}",
                json_body={"configuration_revision": revision, "confirmation": True},
                headers={"Idempotency-Key": self._key(f"runtime-{action}")},
            ).json()
            self._wait_operation(operation["operation_id"], timeout=120)
        reconcile = self._request(
            "POST",
            "/api/v1/components/cc-connect:reconcile",
            json_body={"configuration_revision": revision, "confirmation": True},
            headers={"Idempotency-Key": self._key("runtime-reconcile")},
        ).json()
        self._wait_operation(reconcile["operation_id"], timeout=45)
        status = self._request("GET", "/api/v1/components/cc-connect/lifecycle").json()
        if not self._runtime_ready(status, revision):
            raise GuiApiError(
                "cc-connect 没有通过 PID、可执行文件、配置版本、端口和稳定窗口检查。",
                code="CC_CONNECT_RUNTIME_NOT_READY",
            )

    @staticmethod
    def _runtime_ready(status: dict[str, Any], expected_revision: int) -> bool:
        health = status.get("health") or {}
        identity = status.get("identity") or {}
        verification = status.get("identity_verification") or {}
        pid = status.get("pid")
        return bool(
            status.get("observed_state") == "running_partial"
            and status.get("configuration_revision") == expected_revision
            and pid
            and identity.get("pid") == pid
            and identity.get("configuration_revision") == expected_revision
            and verification.get("status") == "verified"
            and health.get("process_identity_verified")
            and health.get("artifact_integrity_verified")
            and health.get("configuration_revision_verified")
            and health.get("port_owned_by_process")
            and health.get("startup_stable_for_window")
            and not health.get("fatal_log_detected")
        )

    def _ensure_cc_connect_installed(self) -> None:
        versions = self._request("GET", "/api/v1/components/cc-connect/managed-versions").json()
        if any(item.get("current") and item.get("status") == "installed" for item in versions):
            return
        if self.artifact_dir is None:
            raise GuiApiError(
                "运行环境还没有准备好，请先提供锁定的 cc-connect 候选包。",
                code="CC_CONNECT_INSTALL_REQUIRED",
            )
        manifest_path = self.artifact_dir / "cc-connect-artifact-manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            expected_digest = f"sha256:{manifest['artifact_sha256']}"
            requested_version = str(manifest["version"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise GuiApiError(
                "锁定的 cc-connect 候选包无法读取，请重新获取候选包。",
                code="CC_CONNECT_ARTIFACT_INVALID",
            ) from exc
        plan = self._request(
            "POST",
            "/api/v1/components/cc-connect/install-plan",
            json_body={"source_ref": "trusted-local-bundle", "expected_digest": expected_digest},
        ).json()
        operation = self._request(
            "POST",
            "/api/v1/components/cc-connect:install",
            json_body={
                "version_policy": "exact",
                "requested_version": requested_version,
                "source_ref": "trusted-local-bundle",
                "expected_digest": expected_digest,
                "confirm": True,
                "plan_id": plan["plan_id"],
                "plan_digest": plan["plan_digest"],
                "confirmation": True,
            },
            headers={"Idempotency-Key": self._key("install")},
        ).json()
        self._wait_operation(operation["operation_id"], timeout=90)

    def _ensure_product_ownership(self) -> None:
        owners = self._request("GET", "/api/v1/components/cc-connect/owners").json()
        if (
            owners.get("management_owner") == "product"
            and owners.get("lifecycle_owner") == "product"
        ):
            return
        plan = self._request(
            "POST",
            "/api/v1/components/cc-connect/ownership-plans",
            json_body={"target_lifecycle_owner": "product"},
        ).json()
        operation = self._request(
            "POST",
            "/api/v1/components/cc-connect/ownership:confirm",
            json_body={
                "plan_id": plan["plan_id"],
                "plan_digest": plan["plan_digest"],
                "current_management_owner": plan["current_management_owner"],
                "current_lifecycle_owner": plan["current_lifecycle_owner"],
                "confirmation": True,
            },
            headers={"Idempotency-Key": self._key("ownership")},
        ).json()
        self._wait_operation(operation["operation_id"], timeout=45)

    def _ensure_native_configuration(self, session_id: str) -> None:
        state = self._request("GET", "/api/v1/components/cc-connect/native-configuration").json()
        managed_state = state.get("managed_state") or {}
        if state.get("status") == "valid" and managed_state.get("binding_session_id") == session_id:
            return
        base = self.data_dir or Path.cwd()
        claude_root = base / "workspaces" / "claude"
        codex_root = base / "workspaces" / "codex"
        claude_root.mkdir(parents=True, exist_ok=True)
        codex_root.mkdir(parents=True, exist_ok=True)
        plan = self._request(
            "POST",
            "/api/v1/components/cc-connect/native-configuration-plans",
            json_body={
                "binding_session_id": session_id,
                "claude_workspace_root": str(claude_root),
                "codex_workspace_root": str(codex_root),
                "management_port": 59020,
            },
        ).json()
        operation = self._request(
            "POST",
            "/api/v1/components/cc-connect/native-configuration:apply",
            json_body={
                "plan_id": plan["plan_id"],
                "plan_digest": plan["plan_digest"],
                "current_revision": plan["current_revision"],
                "target_revision": plan["target_revision"],
                "confirmation": True,
            },
            headers={"Idempotency-Key": self._key("native-config")},
        ).json()
        self._wait_operation(operation["operation_id"], timeout=90)

    def diagnostics(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/v1/diagnostics").json()

    def live_links(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/v1/observability/links").json()

    def run_live_test(self, *, confirmation: bool) -> list[dict[str, Any]]:
        if not confirmation:
            raise GuiApiError("发送真实测试消息前需要明确确认。", code="E2E_CONFIRMATION_REQUIRED")
        results: list[dict[str, Any]] = []
        for link in self.live_links():
            link_id = str(link["link_id"])
            try:
                plan = self._request(
                    "POST",
                    f"/api/v1/observability/links/{link_id}/e2e-plans",
                    json_body={"expires_in_seconds": 300},
                ).json()
                confirmation_body = {
                    "plan_id": plan["plan_id"],
                    "plan_digest": plan["plan_digest"],
                    "link_id": plan["link_id"],
                    "credential_revision": plan["expected_credential_revision"],
                    "binding_session_id": plan["expected_binding_session_id"],
                    "binding_revision": plan["expected_binding_revision"],
                    "configuration_revision": plan["expected_configuration_revision"],
                    "confirmation": True,
                }
                run = self._request(
                    "POST",
                    f"/api/v1/observability/e2e-plans/{plan['plan_id']}:confirm",
                    json_body=confirmation_body,
                    headers={"Idempotency-Key": self._key(f"e2e-{link_id}")},
                ).json()
                results.append(run)
            except GuiApiError as exc:
                results.append(
                    {
                        "link_id": link_id,
                        "lifecycle": "failed",
                        "evidence_level": "observed",
                        "diagnostic_code": exc.code,
                        "user_message": str(exc),
                        "message_count": 1,
                        "automatic_retry": False,
                    }
                )
        return results

    def open_cc_switch(self) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/external-tools/cc-switch:launch",
            json_body={"confirmation": True},
        ).json()


class EmbeddedControlPlaneClient(HttpControlPlaneClient):
    """Run the existing Control Plane in-process behind the stable HTTP contract.

    The production GUI never falls back to synthetic data.  When no externally
    launched loopback Control Plane is supplied, this client owns one FastAPI
    lifespan for the lifetime of the window.  It uses the same routers,
    credential service and operation executor as the standalone service, while
    keeping all state under the product's per-user data directory.
    """

    def __init__(
        self,
        *,
        data_dir: Path | None = None,
        artifact_dir: Path | None = None,
    ) -> None:
        from fastapi.testclient import TestClient

        from control_plane.api.app import create_app
        from control_plane.infrastructure.config import Settings

        token = os.environ.get("CONTROL_PLANE_API_TOKEN") or secrets.token_urlsafe(32)
        os.environ["CONTROL_PLANE_API_TOKEN"] = token
        resolved_data_dir = data_dir or Path(Settings().data_dir)
        settings = Settings(
            data_dir=str(resolved_data_dir),
            trusted_artifact_dir=(
                str(artifact_dir) if artifact_dir and artifact_dir.is_dir() else None
            ),
        )
        self._embedded_app = create_app(settings)
        self._embedded_client: Any = TestClient(
            self._embedded_app,
            base_url="http://127.0.0.1",
            raise_server_exceptions=False,
        )
        self._embedded_client.__enter__()
        super().__init__(
            "http://embedded-control-plane",
            token,
            data_dir=resolved_data_dir,
            artifact_dir=artifact_dir,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ):
        merged = dict(self.headers)
        if headers:
            merged.update(headers)
        response = self._embedded_client.request(
            method,
            path,
            headers=merged,
            json=json_body,
            follow_redirects=False,
        )
        if response.status_code >= 400:
            try:
                problem = response.json()
            except ValueError:
                problem = {}
            message = problem.get("user_message") or problem.get("detail") or "本机服务返回了错误。"
            code = problem.get("code") or "CONTROL_PLANE_REQUEST_FAILED"
            raise GuiApiError(str(message), code=str(code))
        return response

    def close(self) -> None:
        client = getattr(self, "_embedded_client", None)
        if client is not None:
            client.__exit__(None, None, None)
            self._embedded_client = None


def candidate_artifact_dir() -> Path | None:
    """Locate the bundled cc-connect payload without probing user configuration."""

    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        candidates.append(executable_dir / "cc-connect")
    source_root = Path(__file__).resolve().parents[2]
    candidates.append(source_root / "build" / "cc-connect")
    candidates.append(source_root / "dist" / "cc-connect")
    for candidate in candidates:
        if (candidate / "cc-connect-artifact-manifest.json").is_file() and (
            candidate / "cc-connect.exe"
        ).is_file():
            return candidate
    return None


class DemoControlPlaneClient(GuiApiClient):
    """Synthetic local contract used for screenshots and disconnected startup.

    It mirrors the API shape and never persists token values.  The title bar
    makes the disconnected state visible so it cannot be mistaken for live
    Telegram verification.
    """

    def __init__(self) -> None:
        self._binding: dict[str, Any] | None = None
        self._private_count = 0
        self._group_count = 0
        self._tokens_ready = False
        self._complete = False
        self._live_verified = False

    @property
    def binding(self) -> dict[str, Any] | None:
        return deepcopy(self._binding) if self._binding else None

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def _agents(self) -> list[dict[str, Any]]:
        agents = []
        for index, slot in enumerate(SLOTS):
            agents.append(
                {
                    "slot": slot,
                    "display_name": DISPLAY_NAMES[slot],
                    "bot_username": f"{slot}_bot" if self._tokens_ready else None,
                    "bot_id": 9100 + index if self._tokens_ready else None,
                    "token_ready": self._tokens_ready,
                    "identity_verified": self._tokens_ready,
                    "installed": self._complete,
                    "connected": None,
                    "version": "demo-1.0" if self._complete else None,
                    "detection_status": "installed" if self._complete else "not_found",
                    "probe_status": "healthy" if self._complete else "not_run",
                    "detection_source": "known_location" if self._complete else "not_found",
                    "diagnostic_code": None,
                    "official_install_url": "https://example.invalid/install",
                    "acceptable": self._complete,
                    "private_status": "bound" if index < self._private_count else "pending",
                    "group_status": "bound" if index < self._group_count else "pending",
                    "user_message": "已准备好" if self._tokens_ready else "请输入这个 Bot 的 Token",
                }
            )
        return agents

    def snapshot(self) -> dict[str, Any]:
        step = 1
        if self._tokens_ready:
            step = 2
        if self._private_count == 3:
            step = 3
        if self._group_count == 3:
            step = 4
        return {
            "revision": f"demo-{step}-{self._private_count}-{self._group_count}",
            "observed_at": self._now(),
            "current_step": step,
            "onboarding_complete": self._complete,
            "agents": self._agents(),
            "binding": {
                "session_id": self._binding.get("session_id") if self._binding else None,
                "state": "completed" if self._group_count == 3 else "waiting",
                "expires_at": self._binding.get("expires_at") if self._binding else None,
                "bound_private_count": self._private_count,
                "bound_group_count": self._group_count,
                "group_title": "AI Agent 测试群" if self._group_count == 3 else None,
                "group_type": "supergroup" if self._group_count == 3 else None,
                "revision": step,
            },
            "checklist": [
                {
                    "key": "telegram",
                    "label": "检查 Telegram 连接",
                    "status": "complete" if self._tokens_ready else "needs_action",
                    "user_message": "Telegram 已准备好",
                },
                {
                    "key": "agents",
                    "label": "检查 Hermes、Claude Code 和 Codex",
                    "status": "complete" if self._tokens_ready else "pending",
                    "user_message": "三个 Bot 身份已确认",
                },
                {
                    "key": "runtime",
                    "label": "准备运行环境",
                    "status": "complete" if self._group_count == 3 else "pending",
                    "user_message": "运行环境已准备",
                },
                {
                    "key": "configuration",
                    "label": "生成连接配置",
                    "status": "complete" if self._group_count == 3 else "pending",
                    "user_message": "连接配置已生成",
                },
                {
                    "key": "chat",
                    "label": "检查聊天是否可用",
                    "status": "complete" if self._group_count == 3 else "pending",
                    "user_message": "可以开始使用",
                },
            ],
            "runtime": {
                "ready": self._complete,
                "observed_state": "running_partial" if self._complete else "stopped",
                "pid_verified": self._complete,
                "executable_verified": self._complete,
                "configuration_revision_verified": self._complete,
                "port_owned_by_process": self._complete,
                "startup_stable_for_window": self._complete,
                "configuration_revision": 1 if self._complete else 0,
                "diagnostic_code": None if self._complete else "CC_CONNECT_RUNTIME_NOT_READY",
                "user_message": "演示运行环境已准备" if self._complete else "演示运行环境未准备",
            },
            "chat_health": "live_verified"
            if self._live_verified
            else ("ready_for_test" if self._complete else "unknown"),
            "chat_links": [
                {
                    "link_id": f"{slot}.{kind}",
                    "slot": slot,
                    "scope": kind,
                    "binding_status": "bound" if self._group_count == 3 else "pending",
                    "health_status": "live_verified"
                    if self._live_verified
                    else ("ready_for_test" if self._complete else "unknown"),
                    "user_message": "已验证"
                    if self._live_verified
                    else ("已绑定，等待聊天验证" if self._complete else "尚未绑定"),
                    "evidence_level": "live_verified" if self._live_verified else "observed",
                    "diagnostic_code": None,
                    "correlation_id": None,
                    "request_message_id": None,
                    "response_message_id": None,
                    "latency_ms": None,
                }
                for slot in SLOTS
                for kind in ("private", "group")
            ],
            "cc_switch_installed": False,
            "cc_switch_openable": False,
            "telegram_client": {
                "tg_handler_available": True,
                "https_deep_link_available": True,
                "checked_at": self._now(),
                "official_download_url": "https://desktop.telegram.org/",
            },
            "overall_status": "ready" if self._complete else "needs_action",
        }

    def dashboard_snapshot(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        return {
            "revision": snapshot["revision"],
            "observed_at": snapshot["observed_at"],
            "overall_status": snapshot["overall_status"],
            "telegram_status": "ready" if self._private_count == 3 else "needs_action",
            "runtime": snapshot["runtime"],
            "chat_health": snapshot["chat_health"],
            "agents": [
                {
                    "slot": agent["slot"],
                    "display_name": agent["display_name"],
                    "installed": agent["installed"],
                    "connected": agent["connected"],
                    "version": agent["version"],
                    "detection_status": agent["detection_status"],
                    "probe_status": agent["probe_status"],
                    "official_install_url": agent["official_install_url"],
                    "status": "ready" if agent["acceptable"] else "needs_action",
                    "user_message": agent["user_message"],
                }
                for agent in snapshot["agents"]
            ],
            "chat_links": snapshot["chat_links"],
            "cc_switch_installed": snapshot["cc_switch_installed"],
            "cc_switch_openable": snapshot["cc_switch_openable"],
            "chat_pills": [
                "Hermes 私聊",
                "Hermes 群聊",
                "Claude 私聊",
                "Claude 群聊",
                "Codex 私聊",
                "Codex 群聊",
            ],
            "recent_issues": [] if self._complete else ["快速配置还没有完成，可以从当前步骤继续。"],
        }

    def save_and_verify_tokens(self, tokens: dict[str, str]) -> dict[str, Any]:
        for slot in SLOTS:
            if len(tokens.get(slot, "").strip()) < 12:
                raise GuiApiError(
                    f"{DISPLAY_NAMES[slot]} Bot Token 格式不完整。", code="TOKEN_INVALID"
                )
        self._tokens_ready = True
        return self.snapshot()

    def begin_binding(self) -> dict[str, Any]:
        expiry = datetime.now(UTC) + timedelta(minutes=15)
        code = secrets.token_urlsafe(8).replace("-", "A").replace("_", "B")
        self._binding = {
            "session_id": f"demo-{secrets.token_hex(5)}",
            "expires_at": expiry.isoformat(),
            "private_deep_links": {
                slot: f"https://t.me/{slot}_bot?start=bind_{slot}_{code}" for slot in SLOTS
            },
            "group_deep_links": {
                slot: f"https://t.me/{slot}_bot?startgroup=bind_{slot}_{code}" for slot in SLOTS
            },
        }
        return deepcopy(self._binding)

    def resume_binding(self, session_id: str) -> dict[str, Any]:
        if self._binding is None or self._binding.get("session_id") != session_id:
            raise GuiApiError(
                "Binding session is not available in this demo client.",
                code="TELEGRAM_BINDING_NOT_FOUND",
            )
        expiry = datetime.now(UTC) + timedelta(minutes=15)
        code = secrets.token_urlsafe(8).replace("-", "A").replace("_", "B")
        self._binding["expires_at"] = expiry.isoformat()
        self._binding["private_deep_links"] = {
            slot: f"https://t.me/{slot}_bot?start=bind_{slot}_{code}" for slot in SLOTS
        }
        self._binding["group_deep_links"] = {
            slot: f"https://t.me/{slot}_bot?startgroup=bind_{slot}_{code}" for slot in SLOTS
        }
        return deepcopy(self._binding)

    def poll_binding(self) -> dict[str, Any]:
        if self._binding is None:
            self.begin_binding()
        if self._private_count < 3:
            self._private_count += 1
        elif self._group_count < 3:
            self._group_count = 3
        assert self._binding is not None
        result = deepcopy(self._binding)
        result.update(self.snapshot()["binding"])
        return result

    def complete_configuration(self) -> dict[str, Any]:
        self._tokens_ready = True
        self._complete = True
        return self.snapshot()

    def run_live_test(self, *, confirmation: bool) -> list[dict[str, Any]]:
        if not confirmation:
            raise GuiApiError("发送真实测试消息前需要明确确认。", code="E2E_CONFIRMATION_REQUIRED")
        self._live_verified = True
        return [
            {
                "link_id": f"{slot}.{kind}",
                "lifecycle": "succeeded",
                "evidence_level": "live_verified",
                "message_count": 1,
                "automatic_retry": False,
            }
            for slot in SLOTS
            for kind in ("private", "group")
        ]

    def diagnostics(self) -> list[dict[str, Any]]:
        if self._complete:
            return []
        return [
            {
                "code": "ONBOARDING_INCOMPLETE",
                "severity": "info",
                "user_message": "快速配置还没有完成，可以从当前步骤继续。",
                "suggested_actions": ["resume_onboarding"],
            }
        ]
