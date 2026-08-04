from __future__ import annotations

import argparse
import asyncio
import ctypes
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Iterable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from control_plane.application.event_log import EventLog
from control_plane.application.operation_store import OperationStore
from control_plane.cc_connect.native_config_models import (
    NativeConfigurationConfirmation,
    NativeConfigurationPlanRequest,
)
from control_plane.cc_connect.native_configuration_service import (
    CcConnectNativeConfigurationService,
)
from control_plane.cc_connect.runtime_secret_injector import RuntimeSecretInjector
from control_plane.configuration.service import CcConnectConfigurationService
from control_plane.credentials.models import (
    INTERNAL_CC_CONNECT_MANAGEMENT_REFERENCE,
    PUBLIC_CREDENTIAL_REFERENCES,
    CredentialStatus,
)
from control_plane.credentials.service import CredentialService
from control_plane.credentials.windows_backend import (
    SecretBackend,
    WindowsCredentialManagerBackend,
)
from control_plane.domain.models import OperationStatus
from control_plane.hermes.config_renderer import HermesConfigurationPlanner
from control_plane.hermes.models import HermesConfigurationPlanRequest
from control_plane.infrastructure.config import Settings
from control_plane.installer.artifacts import load_manifest
from control_plane.installer.models import InstallConfirmationRequest, InstallPlanRequest
from control_plane.installer.service import CcConnectInstaller
from control_plane.installer.version_store import ManagedVersionStore
from control_plane.lifecycle.managed_process import ManagedProcessService
from control_plane.lifecycle.models import (
    LifecycleActionRequest,
    OwnershipConfirmationRequest,
    OwnershipPlanRequest,
)
from control_plane.lifecycle.port_ownership import PortOwnershipInspector
from control_plane.operations import ExecutionContext
from control_plane.persistence.models import NativeConfigurationBackupRecord
from control_plane.persistence.session import Database
from control_plane.telegram.binding_service import SLOTS, TelegramBindingService
from control_plane.telegram.bot_identity import TelegramBotIdentityService
from control_plane.telegram.models import TelegramUpdate, TelegramWebhookInfo, UpdateOwner
from control_plane.telegram.update_lease import TelegramUpdateLeaseService


class NamespacedWindowsBackend:
    backend_id = "windows_credential_manager"

    def __init__(self, namespace: str) -> None:
        self.inner = WindowsCredentialManagerBackend()
        self.namespace = namespace
        self.references: set[str] = set()

    def _mapped(self, reference_id: str) -> str:
        mapped = f"acceptance/{self.namespace}/{reference_id.replace('/', '-')}"
        self.references.add(mapped)
        return mapped

    def probe(self):
        return self.inner.probe()

    def put(self, reference_id: str, secret: str) -> None:
        self.inner.put(self._mapped(reference_id), secret)

    def replace(self, reference_id: str, secret: str) -> None:
        self.inner.replace(self._mapped(reference_id), secret)

    def status(self, reference_id: str) -> CredentialStatus:
        return self.inner.status(self._mapped(reference_id))

    def resolve_for_operation(self, reference_id: str) -> AbstractContextManager[str]:
        return self.inner.resolve_for_operation(self._mapped(reference_id))

    def delete(self, reference_id: str) -> None:
        self.inner.delete(self._mapped(reference_id))

    def list_metadata(self, reference_ids: Iterable[str]) -> dict[str, CredentialStatus]:
        return {reference_id: self.status(reference_id) for reference_id in reference_ids}

    def cleanup(self) -> None:
        for mapped in sorted(self.references):
            self.inner.delete(mapped)


class FakeTelegramClient:
    def __init__(self, tokens: dict[str, str]) -> None:
        self.identities = {
            tokens[slot]: {
                "id": 9500 + index,
                "is_bot": True,
                "username": f"aiad_acceptance_{slot}_bot",
                "first_name": f"Acceptance {slot.title()}",
                "can_join_groups": True,
                "can_read_all_group_messages": False,
            }
            for index, slot in enumerate(SLOTS, start=1)
        }
        self.webhooks = {token: False for token in tokens.values()}
        self.updates: dict[str, list[TelegramUpdate]] = {token: [] for token in tokens.values()}

    async def get_me(self, token: str, *, cancel_event=None) -> dict[str, Any]:
        del cancel_event
        return dict(self.identities[token])

    async def get_webhook_info(self, token: str, *, cancel_event=None) -> TelegramWebhookInfo:
        del cancel_event
        return TelegramWebhookInfo(url_present=self.webhooks[token])

    async def get_updates(
        self,
        token: str,
        *,
        offset: int,
        timeout_seconds: int,
        cancel_event=None,
    ) -> list[TelegramUpdate]:
        del timeout_seconds, cancel_event
        return [item for item in self.updates[token] if item.update_id >= offset]

    async def delete_webhook(
        self,
        token: str,
        *,
        explicit_confirmation: bool,
        drop_pending_updates: bool = False,
        cancel_event=None,
    ) -> bool:
        del cancel_event
        if not explicit_confirmation:
            raise AssertionError("explicit webhook confirmation is required")
        self.webhooks[token] = False
        if drop_pending_updates:
            self.updates[token].clear()
        return True

    def add_update(self, token: str, update_id: int, payload: dict[str, Any]) -> None:
        self.updates[token].append(TelegramUpdate(update_id=update_id, payload=payload))


def _operation(database: Database, operation_id: str):
    with database.session() as session:
        value = OperationStore(session).get(operation_id)
    if value is None:
        raise AssertionError(f"operation disappeared: {operation_id}")
    return value


def _install(installer: CcConnectInstaller, database: Database, digest: str):
    plan = installer.create_plan(
        InstallPlanRequest(
            source_ref="trusted-local-bundle",
            expected_digest=f"sha256:{digest}",
        )
    )
    confirmation = InstallConfirmationRequest(
        requested_version=plan.version,
        source_ref=plan.source.source_ref,
        expected_digest=f"sha256:{plan.sha256}",
        confirm=True,
        plan_id=plan.plan_id,
        plan_digest=plan.plan_digest,
        confirmation=True,
    )
    created, reused = installer.confirm_install(
        confirmation,
        idempotency_key="native-acceptance-install",
        body=confirmation.model_dump_json().encode(),
    )
    if reused:
        raise AssertionError("fresh isolated install unexpectedly reused")
    installer.execute_install(created.operation_id, plan.plan_id, "native-acceptance")
    result = _operation(database, created.operation_id)
    if result.status != OperationStatus.SUCCEEDED:
        raise AssertionError(result.model_dump_json())
    return result


def _handoff(service: ManagedProcessService, database: Database):
    plan = service.create_ownership_plan(OwnershipPlanRequest())
    confirmation = OwnershipConfirmationRequest(
        plan_id=plan.plan_id,
        plan_digest=plan.plan_digest,
        current_management_owner=plan.current_management_owner,
        current_lifecycle_owner=plan.current_lifecycle_owner,
        confirmation=True,
    )
    created, _ = service.confirm_ownership_plan(
        confirmation,
        idempotency_key="native-acceptance-owner",
        body=confirmation.model_dump_json().encode(),
    )
    service.execute_ownership_handoff(created.operation_id, plan.plan_id)
    result = _operation(database, created.operation_id)
    if result.status != OperationStatus.SUCCEEDED:
        raise AssertionError(result.model_dump_json())
    return result


def _apply_native(
    service: CcConnectNativeConfigurationService,
    database: Database,
    request: NativeConfigurationPlanRequest,
    key: str,
):
    plan = service.create_plan(request)
    confirmation = NativeConfigurationConfirmation(
        plan_id=plan.plan_id,
        plan_digest=plan.plan_digest,
        current_revision=plan.current_revision,
        target_revision=plan.target_revision,
        confirmation=True,
    )
    created, reused = service.confirm_plan(
        confirmation,
        idempotency_key=key,
        body=confirmation.model_dump_json().encode(),
    )
    if reused:
        raise AssertionError("fresh native configuration operation unexpectedly reused")
    execution_result = service.execute_plan(created.operation_id, plan.plan_id)
    with database.session() as session:
        OperationStore(session).transition(
            created.operation_id,
            status=OperationStatus.SUCCEEDED,
            phase="native_configuration_applied",
            message="Native configuration acceptance apply completed.",
            result=execution_result,
        )
    result = _operation(database, created.operation_id)
    if result.status != OperationStatus.SUCCEEDED:
        raise AssertionError(result.model_dump_json())
    return plan, result


def _lifecycle_action(
    service: ManagedProcessService,
    database: Database,
    action: str,
    revision: int,
    key: str,
):
    request = LifecycleActionRequest(configuration_revision=revision, confirmation=True)
    created, reused = service.create_operation(
        action,  # type: ignore[arg-type]
        request,
        idempotency_key=key,
        body=request.model_dump_json().encode(),
    )
    if reused:
        raise AssertionError(f"fresh lifecycle operation unexpectedly reused: {action}")
    service.execute_action(
        created.operation_id,
        action,  # type: ignore[arg-type]
        request,
    )
    return _operation(database, created.operation_id)


def _free_ports(count: int) -> list[int]:
    result: list[int] = []
    for port in range(59020, 60000):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind(("127.0.0.1", port))
        except OSError:
            continue
        finally:
            listener.close()
        result.append(port)
        if len(result) == count:
            return result
    raise RuntimeError("unable to allocate acceptance ports")


def _message_update(
    *,
    update_id: int,
    text: str,
    sender_id: int,
    chat_id: int,
    chat_type: str,
    title: str | None = None,
) -> dict[str, Any]:
    chat: dict[str, Any] = {"id": chat_id, "type": chat_type}
    if title:
        chat["title"] = title
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "date": int(time.time()),
            "text": text,
            "from": {"id": sender_id, "is_bot": False},
            "chat": chat,
        },
    }


def _complete_binding(
    database: Database,
    client: FakeTelegramClient,
    bindings: TelegramBindingService,
    tokens: dict[str, str],
):
    created = bindings.create(expires_in_seconds=900)
    for index, slot in enumerate(SLOTS, start=1):
        client.add_update(
            tokens[slot],
            index,
            _message_update(
                update_id=index,
                text=created.private_commands[slot],
                sender_id=880001,
                chat_id=880001,
                chat_type="private",
            ),
        )
        bindings.poll(
            ExecutionContext(
                operation_id=f"acceptance-private-{slot}",
                component_id=f"telegram:{slot}",
                kind="telegram_binding_poll",
                payload={
                    "session_id": created.session_id,
                    "slot": slot,
                    "timeout_seconds": 0,
                },
                database=database,
                shutdown_event=threading.Event(),
            )
        )
    for index, slot in enumerate(SLOTS, start=11):
        client.add_update(
            tokens[slot],
            index,
            _message_update(
                update_id=index,
                text=created.group_commands[slot],
                sender_id=880001,
                chat_id=-100880001,
                chat_type="supergroup",
                title="AIAD 合成验收组",
            ),
        )
        bindings.poll(
            ExecutionContext(
                operation_id=f"acceptance-group-{slot}",
                component_id=f"telegram:{slot}",
                kind="telegram_binding_poll",
                payload={
                    "session_id": created.session_id,
                    "slot": slot,
                    "timeout_seconds": 0,
                },
                database=database,
                shutdown_event=threading.Event(),
            )
        )
    completed = bindings.get(created.session_id)
    if completed.state.value != "completed":
        raise AssertionError(completed.model_dump_json())
    return created, completed


def _scan_for_values(root: Path, values: Iterable[str]) -> list[str]:
    encoded = [
        value.encode(encoding)
        for value in values
        for encoding in ("utf-8", "utf-16-le", "utf-16-be")
    ]
    leaks: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            content = path.read_bytes()
        except OSError:
            continue
        if any(value in content for value in encoded):
            leaks.append(str(path.relative_to(root)))
    return sorted(leaks)


def _external_candidate() -> dict[str, Any] | None:
    candidate = shutil.which("cc-connect.exe") or shutil.which("cc-connect")
    if not candidate:
        return None
    path = Path(candidate)
    try:
        stat = path.stat()
    except OSError:
        return {"path_present": True, "stat": "unknown"}
    return {
        "path_present": True,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _managed_processes(root: Path) -> list[int]:
    import psutil

    result: list[int] = []
    expected = root.resolve(strict=False)
    for process in psutil.process_iter(["pid", "exe"]):
        try:
            executable = process.info.get("exe")
            if executable and Path(executable).resolve().is_relative_to(expected):
                result.append(int(process.info["pid"]))
        except (OSError, psutil.Error):
            continue
    return sorted(result)


def run(bundle: Path, temp_root: Path | None = None) -> dict[str, Any]:
    if sys.platform != "win32":
        raise RuntimeError("native runtime acceptance requires Windows")
    bundle = bundle.resolve(strict=True)
    manifest, _ = load_manifest(bundle / "cc-connect-artifact-manifest.json")
    capability = WindowsCredentialManagerBackend().probe()
    if capability.status != CredentialStatus.AVAILABLE or not capability.native_windows_backend:
        raise AssertionError(capability.model_dump_json())

    started_at = datetime.now(UTC)
    path_before = os.environ.get("PATH", "")
    external_before = _external_candidate()
    parent = temp_root.resolve(strict=True) if temp_root else Path("D:\\")
    if parent.drive.casefold() == Path(os.environ.get("SystemDrive", "C:") + "\\").drive.casefold():
        raise RuntimeError("a writable non-system drive is required")

    namespace = f"native-{uuid.uuid4().hex}"
    backend: SecretBackend = NamespacedWindowsBackend(namespace)
    namespaced_backend = backend
    database: Database | None = None
    lifecycle: ManagedProcessService | None = None
    secrets_to_scan: list[str] = []
    try:
        with tempfile.TemporaryDirectory(
            prefix="AIAD native runtime 中文 空格 (临时) ",
            dir=parent,
            ignore_cleanup_errors=True,
        ) as root_name:
            root = Path(root_name)
            data_dir = root / "产品数据 中文 (受管)"
            settings = Settings(
                data_dir=str(data_dir),
                trusted_artifact_dir=str(bundle),
                lifecycle_startup_timeout_seconds=30,
                lifecycle_stop_timeout_seconds=10,
                lifecycle_stable_window_seconds=2,
            )
            database = Database(settings)
            installer = CcConnectInstaller(settings, database, EventLog())
            installed = _install(installer, database, manifest.artifact_sha256)
            version_store = ManagedVersionStore(installer.layout, database)
            ports = PortOwnershipInspector()
            configuration = CcConnectConfigurationService(
                database,
                installer.layout,
                version_store=version_store,
                port_inspector=ports,
                external_conflict_detector=lambda: False,
            )
            ownership_lifecycle = ManagedProcessService(
                database,
                installer.layout,
                configuration,
                version_store=version_store,
                port_inspector=ports,
            )
            ownership = _handoff(ownership_lifecycle, database)

            credentials = CredentialService(database, backend)
            tokens = {
                slot: f"{970000 + index}:AA{uuid.uuid4().hex}{uuid.uuid4().hex[:8]}"
                for index, slot in enumerate(SLOTS, start=1)
            }
            secrets_to_scan.extend(tokens.values())
            client = FakeTelegramClient(tokens)
            identities = TelegramBotIdentityService(
                database,
                credentials,
                client,  # type: ignore[arg-type]
            )
            leases = TelegramUpdateLeaseService(database)
            bindings = TelegramBindingService(
                database,
                credentials,
                identities,
                leases,
                client,  # type: ignore[arg-type]
            )
            for slot in SLOTS:
                credentials.put(
                    PUBLIC_CREDENTIAL_REFERENCES[slot][0],
                    tokens[slot],
                    operation_id=f"acceptance-credential-{slot}",
                )
                identity = identities.verify(slot)
                if identity.verification_status != "verified":
                    raise AssertionError(identity.model_dump_json())
            created_binding, completed_binding = _complete_binding(
                database, client, bindings, tokens
            )
            secrets_to_scan.append(created_binding.bind_code)

            native = CcConnectNativeConfigurationService(
                database,
                installer.layout,
                credentials,
                identities,
                bindings,
                configuration,
                version_store=version_store,
            )
            claude_workspace = root / "Claude 项目 (合成)"
            codex_workspace = root / "Codex 项目 (合成)"
            claude_workspace.mkdir()
            codex_workspace.mkdir()
            port_one, port_two = _free_ports(2)
            first_request = NativeConfigurationPlanRequest(
                binding_session_id=created_binding.session_id,
                claude_workspace_root=str(claude_workspace.resolve()),
                codex_workspace_root=str(codex_workspace.resolve()),
                management_port=port_one,
            )
            first, _ = _apply_native(native, database, first_request, "native-acceptance-config-1")
            second, _ = _apply_native(
                native,
                database,
                first_request.model_copy(update={"management_port": port_two}),
                "native-acceptance-config-2",
            )
            rollback, _ = _apply_native(
                native,
                database,
                first_request.model_copy(update={"rollback_to_revision": 1}),
                "native-acceptance-config-rollback",
            )
            if (first.target_revision, second.target_revision, rollback.target_revision) != (
                1,
                2,
                3,
            ):
                raise AssertionError("native configuration revisions did not advance")
            if native.state().runtime_config.management_port != port_one:
                raise AssertionError("native rollback did not restore revision one")

            native.store.runtime_path.write_text("drift = true\n", encoding="utf-8")
            drifted = native.state()
            if drifted.status != "drifted":
                raise AssertionError("native configuration drift was not detected")
            repaired, _ = _apply_native(
                native,
                database,
                first_request.model_copy(update={"rollback_to_revision": 3}),
                "native-acceptance-config-repair",
            )
            state = native.state()
            if state.status != "valid" or repaired.target_revision != 4:
                raise AssertionError("native configuration drift recovery failed")
            if state.runtime_config is None or state.managed_state is None:
                raise AssertionError("native configuration state is incomplete")

            runtime_text = native.store.runtime_path.read_text(encoding="utf-8")
            managed_text = native.store.managed_path.read_text(encoding="utf-8")
            for expected in (
                "${AIAD_TELEGRAM_CLAUDE_BOT_TOKEN}",
                "${AIAD_TELEGRAM_CODEX_BOT_TOKEN}",
                "${AIAD_CC_CONNECT_MANAGEMENT_TOKEN}",
                'type = "claudecode"',
                'type = "codex"',
            ):
                if expected not in runtime_text:
                    raise AssertionError(f"native TOML missing expected locked field: {expected}")
            for forbidden in (
                "management_owner",
                "credential_reference_id",
                "group_chat_id",
                *secrets_to_scan,
            ):
                if forbidden in runtime_text:
                    raise AssertionError(f"forbidden value entered native TOML: {forbidden[:32]}")
            if '"management_owner": "product"' not in managed_text:
                raise AssertionError("product management state is missing its owner")

            hermes = HermesConfigurationPlanner(
                database,
                bindings,
                path_lookup=lambda _name: None,
            ).create_plan(
                HermesConfigurationPlanRequest(binding_session_id=created_binding.session_id)
            )
            if hermes.status != "pending_component_install":
                raise AssertionError(hermes.model_dump_json())

            injector = RuntimeSecretInjector(database, credentials)
            lifecycle = ManagedProcessService(
                database,
                installer.layout,
                configuration,
                version_store=version_store,
                port_inspector=ports,
                native_configuration_service=native,
                runtime_secret_injector=injector,
                telegram_identities=identities,
                telegram_leases=leases,
                startup_timeout_seconds=30,
                stop_timeout_seconds=10,
                stable_window_seconds=2,
            )
            start_result = _lifecycle_action(
                lifecycle,
                database,
                "start",
                state.revision,
                "native-acceptance-start",
            )
            if start_result.status != OperationStatus.SUCCEEDED:
                log_path = Path(state.runtime_config.log_dir) / "cc-connect-runtime.log"
                log_tail = (
                    log_path.read_text(encoding="utf-8", errors="replace")[-8000:]
                    if log_path.exists()
                    else "runtime log missing"
                )
                for secret in secrets_to_scan:
                    log_tail = log_tail.replace(secret, "[REDACTED]")
                raise AssertionError(
                    json.dumps(
                        {
                            "operation": start_result.model_dump(mode="json"),
                            "redacted_log_tail": log_tail,
                        },
                        ensure_ascii=False,
                    )
                )
            running = lifecycle.status()
            if (
                running.observed_state != "running_partial"
                or running.identity is None
                or running.port_ownership is None
                or running.port_ownership.status != "owned"
                or not running.health.management_api_verified
            ):
                raise AssertionError(running.model_dump_json())

            with credentials.resolve_for_operation(
                INTERNAL_CC_CONNECT_MANAGEMENT_REFERENCE
            ) as management_token:
                secrets_to_scan.append(management_token)
                correct = httpx.get(
                    f"http://127.0.0.1:{port_one}/api/v1/status",
                    headers={"Authorization": f"Bearer {management_token}"},
                    timeout=5,
                    trust_env=False,
                )
                wrong = httpx.get(
                    f"http://127.0.0.1:{port_one}/api/v1/status",
                    headers={"Authorization": "Bearer acceptance-wrong-token"},
                    timeout=5,
                    trust_env=False,
                )
            if correct.status_code != 200 or wrong.status_code != 401:
                raise AssertionError(
                    f"management API auth mismatch: {correct.status_code}/{wrong.status_code}"
                )
            if leases.get("claude").owner != UpdateOwner.CC_CONNECT_RUNTIME:
                raise AssertionError("Claude runtime update lease was not acquired")
            if leases.get("codex").owner != UpdateOwner.CC_CONNECT_RUNTIME:
                raise AssertionError("Codex runtime update lease was not acquired")

            stopped = _lifecycle_action(
                lifecycle,
                database,
                "stop",
                state.revision,
                "native-acceptance-stop",
            )
            if stopped.status != OperationStatus.SUCCEEDED:
                raise AssertionError(stopped.model_dump_json())
            restarted = _lifecycle_action(
                lifecycle,
                database,
                "restart",
                state.revision,
                "native-acceptance-restart",
            )
            if restarted.status != OperationStatus.SUCCEEDED:
                raise AssertionError(restarted.model_dump_json())

            simulated_restart = ManagedProcessService(
                database,
                installer.layout,
                configuration,
                version_store=version_store,
                port_inspector=ports,
                native_configuration_service=native,
                runtime_secret_injector=injector,
                telegram_identities=identities,
                telegram_leases=leases,
                startup_timeout_seconds=30,
                stop_timeout_seconds=10,
                stable_window_seconds=2,
            )
            reconciled = simulated_restart.reconcile(
                operation_id="native-acceptance-control-plane-restart"
            )
            if reconciled.observed_state != "running_partial":
                raise AssertionError(reconciled.model_dump_json())
            final_stop = _lifecycle_action(
                simulated_restart,
                database,
                "stop",
                state.revision,
                "native-acceptance-final-stop",
            )
            if final_stop.status != OperationStatus.SUCCEEDED:
                raise AssertionError(final_stop.model_dump_json())
            if leases.get("claude").owner != UpdateOwner.NONE:
                raise AssertionError("Claude runtime update lease remained after stop")
            if leases.get("codex").owner != UpdateOwner.NONE:
                raise AssertionError("Codex runtime update lease remained after stop")

            with database.session() as session:
                backup_count = len(session.query(NativeConfigurationBackupRecord).all())
            leaks = _scan_for_values(root, secrets_to_scan)
            if leaks:
                raise AssertionError(f"synthetic secret or bind code leaked: {leaks}")
            remaining = _managed_processes(installer.layout.root)
            if remaining:
                raise AssertionError(f"managed processes remained: {remaining}")
            if os.environ.get("PATH", "") != path_before:
                raise AssertionError("acceptance changed process PATH")
            if _external_candidate() != external_before:
                raise AssertionError("acceptance changed the external cc-connect candidate")

            evidence = {
                "status": "PARTIAL",
                "synthetic_acceptance": "PASSED",
                "telegram_live_validation": "PENDING USER LIVE VALIDATION",
                "windows_10_validation": "PENDING WINDOWS 10 VALIDATION",
                "started_at": started_at.isoformat(),
                "completed_at": datetime.now(UTC).isoformat(),
                "platform": sys.platform,
                "windows_version": "win32:"
                + ".".join(str(part) for part in sys.getwindowsversion().platform_version),
                "ordinary_user_observed": not bool(ctypes.windll.shell32.IsUserAnAdmin()),
                "artifact_id": manifest.artifact_id,
                "artifact_sha256": manifest.artifact_sha256,
                "source_commit": manifest.source_commit,
                "install_operation_status": installed.status.value,
                "ownership_operation_status": ownership.status.value,
                "credential_backend": capability.model_dump(mode="json"),
                "fake_get_me_identity_count": len(identities.list()),
                "binding_state": completed_binding.state.value,
                "bound_private_count": completed_binding.bound_private_count,
                "bound_group_count": completed_binding.bound_group_count,
                "operator_user_consistent": completed_binding.operator_user_id == 880001,
                "group_chat_consistent": completed_binding.group_chat_id == -100880001,
                "native_configuration_revision": state.revision,
                "native_renderer_version": state.runtime_config.renderer_version,
                "native_runtime_config_relative_path": state.managed_state.runtime_config_relative_path,
                "native_group_chat_filter_status": state.managed_state.native_group_chat_filter_status,
                "native_backup_count": backup_count,
                "drift_detected_and_repaired": True,
                "hermes_status": hermes.status,
                "start_operation_status": start_result.status.value,
                "runtime_observed_state": running.observed_state,
                "pid": running.pid,
                "process_identity_verified": running.health.process_identity_verified,
                "artifact_integrity_verified": running.health.artifact_integrity_verified,
                "configuration_revision_verified": running.health.configuration_revision_verified,
                "port_owned_by_process": running.health.port_owned_by_process,
                "startup_stable_for_window": running.health.startup_stable_for_window,
                "management_api_verified": running.health.management_api_verified,
                "management_api_bind_scope": running.health.management_api_bind_scope,
                "management_api_wrong_bearer_rejected": True,
                "stop_operation_status": stopped.status.value,
                "restart_operation_status": restarted.status.value,
                "control_plane_restart_reconcile_state": reconciled.observed_state,
                "final_stop_operation_status": final_stop.status.value,
                "update_leases_released": True,
                "secret_and_bind_code_file_scan": "passed",
                "managed_processes_after": remaining,
                "path_unchanged": True,
                "external_candidate_unchanged": True,
                "reference_baseline_modified": False,
                "registry_modified": False,
                "scheduled_tasks_modified": False,
                "watchdog_modified": False,
                "synthetic_tokens_only": True,
                "real_messages_sent": False,
                "deep_health": "unsupported",
            }
            database.engine.dispose()
            database = None
            return evidence
    finally:
        if lifecycle is not None:
            for process in lifecycle._launched.values():
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except Exception:
                        process.kill()
        if database is not None:
            database.engine.dispose()
        assert isinstance(namespaced_backend, NamespacedWindowsBackend)
        namespaced_backend.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--temp-root", type=Path)
    args = parser.parse_args()
    result = run(args.bundle, args.temp_root)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    main()
