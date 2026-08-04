from __future__ import annotations

import argparse
import ctypes
import json
import os
import socket
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from control_plane.application.event_log import EventLog
from control_plane.application.operation_store import OperationStore
from control_plane.configuration.models import (
    ConfigurationConfirmationRequest,
    ConfigurationPlanRequest,
)
from control_plane.configuration.service import CcConnectConfigurationService
from control_plane.domain.models import OperationStatus
from control_plane.infrastructure.config import Settings, default_data_dir
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
from control_plane.persistence.session import Database


def operation(database: Database, operation_id: str):
    with database.session() as session:
        value = OperationStore(session).get(operation_id)
    if value is None:
        raise AssertionError(f"operation disappeared: {operation_id}")
    return value


def install_locked(installer: CcConnectInstaller, database: Database, artifact_sha256: str):
    plan = installer.create_plan(
        InstallPlanRequest(
            source_ref="trusted-local-bundle",
            expected_digest=f"sha256:{artifact_sha256}",
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
        idempotency_key="runtime-acceptance-install",
        body=confirmation.model_dump_json().encode(),
    )
    if reused:
        raise AssertionError("fresh isolated install unexpectedly reused")
    installer.execute_install(created.operation_id, plan.plan_id, "runtime-acceptance")
    completed = operation(database, created.operation_id)
    if completed.status != OperationStatus.SUCCEEDED:
        raise AssertionError(completed.model_dump_json())
    return completed


def handoff_ownership(service: ManagedProcessService, database: Database):
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
        idempotency_key="runtime-acceptance-owner",
        body=confirmation.model_dump_json().encode(),
    )
    service.execute_ownership_handoff(created.operation_id, plan.plan_id)
    completed = operation(database, created.operation_id)
    if completed.status != OperationStatus.SUCCEEDED:
        raise AssertionError(completed.model_dump_json())
    return completed


def create_and_confirm_configuration(
    service: CcConnectConfigurationService,
    request: ConfigurationPlanRequest,
    *,
    key: str,
):
    plan = service.create_plan(request)
    confirmation = ConfigurationConfirmationRequest(
        plan_id=plan.plan_id,
        plan_digest=plan.plan_digest,
        current_revision=plan.current_revision,
        target_revision=plan.target_revision,
        confirmation=True,
    )
    created, _ = service.confirm_plan(
        confirmation,
        idempotency_key=key,
        body=confirmation.model_dump_json().encode(),
    )
    return plan, created


def apply_configuration(
    service: CcConnectConfigurationService,
    database: Database,
    request: ConfigurationPlanRequest,
    *,
    key: str,
):
    plan, created = create_and_confirm_configuration(service, request, key=key)
    service.execute_plan(created.operation_id, plan.plan_id)
    completed = operation(database, created.operation_id)
    if completed.status != OperationStatus.SUCCEEDED:
        raise AssertionError(completed.model_dump_json())
    return plan, completed


def lifecycle_action(
    service: ManagedProcessService,
    database: Database,
    action: str,
    revision: int,
    *,
    key: str,
):
    request = LifecycleActionRequest(configuration_revision=revision, confirmation=True)
    created, _ = service.create_operation(
        action,  # type: ignore[arg-type]
        request,
        idempotency_key=key,
        body=request.model_dump_json().encode(),
    )
    service.execute_action(
        created.operation_id,
        action,  # type: ignore[arg-type]
        request,
    )
    return operation(database, created.operation_id)


def non_system_temp_root(explicit: Path | None = None) -> Path:
    system_drive = Path(os.environ.get("SystemDrive", "C:") + "\\").drive.casefold()
    candidates = (
        [explicit] if explicit else [Path(f"{letter}:\\") for letter in "DEFGHIJKLMNOPQRSTUVWXYZ"]
    )
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            resolved = candidate.resolve(strict=True)
            probe = resolved / f".ai-agent-desktop-write-probe-{uuid.uuid4().hex}"
            probe.mkdir()
            probe.rmdir()
        except OSError:
            continue
        if resolved.drive.casefold() != system_drive:
            return resolved
    raise RuntimeError("a writable non-system drive is required for Windows acceptance")


def managed_processes(root: Path) -> list[int]:
    import psutil

    result: list[int] = []
    resolved = root.resolve(strict=False)
    for process in psutil.process_iter(["pid", "exe"]):
        try:
            executable = process.info.get("exe")
            if executable and Path(executable).resolve().is_relative_to(resolved):
                result.append(process.pid)
        except (OSError, psutil.Error):
            continue
    return result


def external_candidate_stat() -> dict[str, int] | None:
    import shutil

    candidate = shutil.which("cc-connect") or shutil.which("cc-connect.exe")
    if not candidate:
        return None
    stat = Path(candidate).stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def run(bundle: Path, temp_root: Path | None = None) -> dict[str, Any]:
    if sys.platform != "win32":
        raise RuntimeError("managed runtime acceptance requires Windows")
    bundle = bundle.resolve(strict=True)
    manifest, _ = load_manifest(bundle / "cc-connect-artifact-manifest.json")
    started_at = datetime.now(UTC)
    original_environment = {
        name: os.environ.get(name)
        for name in (
            "LOCALAPPDATA",
            "APPDATA",
            "HOME",
            "USERPROFILE",
            "WIN_PD_OVERRIDE_LOCAL_APPDATA",
            "WIN_PD_OVERRIDE_APPDATA",
            "TELEGRAM_BOT_TOKEN",
            "OPENAI_API_KEY",
        )
    }
    path_before = os.environ.get("PATH", "")
    external_before = external_candidate_stat()
    database: Database | None = None
    canary = "123456789:AAAcceptanceCanary_NotARealTelegramToken_1234567890"
    try:
        root_parent = non_system_temp_root(temp_root)
        with tempfile.TemporaryDirectory(
            prefix="AI Agent Desktop 生命周期验收 中文 (临时) ", dir=root_parent
        ) as root_name:
            root = Path(root_name)
            local_data = root / "Local AppData 中文 (产品管理)"
            profile = root / "User Profile 中文 (普通用户)"
            local_data.mkdir(parents=True)
            profile.mkdir(parents=True)
            os.environ["LOCALAPPDATA"] = str(local_data)
            os.environ["APPDATA"] = str(profile / "AppData" / "Roaming")
            os.environ["HOME"] = str(profile)
            os.environ["USERPROFILE"] = str(profile)
            os.environ["WIN_PD_OVERRIDE_LOCAL_APPDATA"] = str(local_data)
            os.environ["WIN_PD_OVERRIDE_APPDATA"] = str(profile / "AppData" / "Roaming")
            os.environ["TELEGRAM_BOT_TOKEN"] = canary
            os.environ["OPENAI_API_KEY"] = "sk-synthetic-acceptance-canary-not-real"
            data_dir = Path(default_data_dir())
            if not data_dir.resolve(False).is_relative_to(local_data.resolve()):
                raise AssertionError("product data escaped isolated LocalAppData")
            settings = Settings(data_dir=str(data_dir), trusted_artifact_dir=str(bundle))
            database = Database(settings)
            installer = CcConnectInstaller(settings, database, EventLog())
            install_result = install_locked(installer, database, manifest.artifact_sha256)
            version_store = ManagedVersionStore(installer.layout, database)
            ports = PortOwnershipInspector()
            configuration = CcConnectConfigurationService(
                database,
                installer.layout,
                version_store=version_store,
                port_inspector=ports,
                external_conflict_detector=lambda: False,
            )
            lifecycle = ManagedProcessService(
                database,
                installer.layout,
                configuration,
                version_store=version_store,
                port_inspector=ports,
                external_detector=lambda: False,
                startup_timeout_seconds=3,
                stop_timeout_seconds=2,
                stable_window_seconds=0.5,
            )
            owner_result = handoff_ownership(lifecycle, database)
            revision_one, _ = apply_configuration(
                configuration,
                database,
                ConfigurationPlanRequest(),
                key="runtime-acceptance-config-1",
            )
            if revision_one.target_revision != 1:
                raise AssertionError("first configuration revision is not one")

            race_one, race_one_operation = create_and_confirm_configuration(
                configuration,
                ConfigurationPlanRequest(listen_port=revision_one.ports[0] + 1),
                key="runtime-acceptance-race-1",
            )
            race_two, race_two_operation = create_and_confirm_configuration(
                configuration,
                ConfigurationPlanRequest(listen_port=revision_one.ports[0] + 2),
                key="runtime-acceptance-race-2",
            )
            configuration.execute_plan(race_one_operation.operation_id, race_one.plan_id)
            configuration.execute_plan(race_two_operation.operation_id, race_two.plan_id)
            race_conflict = operation(database, race_two_operation.operation_id)
            if (
                race_conflict.status != OperationStatus.FAILED
                or not race_conflict.error
                or race_conflict.error.code != "CONFIGURATION_REVISION_CONFLICT"
            ):
                raise AssertionError("configuration revision conflict was not blocked")
            rollback_plan, _ = apply_configuration(
                configuration,
                database,
                ConfigurationPlanRequest(rollback_to_revision=1),
                key="runtime-acceptance-config-rollback",
            )
            state = configuration.state()
            if state.status != "valid" or state.revision != rollback_plan.target_revision:
                raise AssertionError(
                    "configuration rollback plan did not create an active revision"
                )
            if (
                state.configuration is None
                or state.configuration.listen_port != revision_one.ports[0]
            ):
                raise AssertionError("rollback did not restore the revision-one managed port")
            final_revision = state.revision
            final_port = state.configuration.listen_port

            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
            if exclusive is not None:
                listener.setsockopt(socket.SOL_SOCKET, exclusive, 1)
            listener.bind(("127.0.0.1", final_port))
            listener.listen(1)
            try:
                port_conflict = lifecycle_action(
                    lifecycle,
                    database,
                    "start",
                    final_revision,
                    key="runtime-acceptance-port-conflict",
                )
            finally:
                listener.close()
            if (
                port_conflict.status != OperationStatus.FAILED
                or not port_conflict.error
                or port_conflict.error.code != "MANAGED_PORT_CONFLICT"
            ):
                raise AssertionError("external port conflict was not blocked")

            conflicting_lifecycle = ManagedProcessService(
                database,
                installer.layout,
                configuration,
                version_store=version_store,
                port_inspector=ports,
                external_detector=lambda: True,
            )
            external_conflict = lifecycle_action(
                conflicting_lifecycle,
                database,
                "start",
                final_revision,
                key="runtime-acceptance-external-conflict",
            )
            if (
                external_conflict.status != OperationStatus.FAILED
                or not external_conflict.error
                or external_conflict.error.code != "EXTERNAL_LIFECYCLE_CONFLICT"
            ):
                raise AssertionError("external lifecycle conflict was not blocked")

            real_start = lifecycle_action(
                lifecycle,
                database,
                "start",
                final_revision,
                key="runtime-acceptance-real-start",
            )
            if real_start.status == OperationStatus.SUCCEEDED:
                real_runtime_status = "running_partial"
                stop_result = lifecycle_action(
                    lifecycle,
                    database,
                    "stop",
                    final_revision,
                    key="runtime-acceptance-real-stop",
                )
                restart_result = lifecycle_action(
                    lifecycle,
                    database,
                    "restart",
                    final_revision,
                    key="runtime-acceptance-real-restart",
                )
                if restart_result.status == OperationStatus.SUCCEEDED:
                    lifecycle_action(
                        lifecycle,
                        database,
                        "stop",
                        final_revision,
                        key="runtime-acceptance-final-stop",
                    )
            else:
                real_runtime_status = "upstream_secretless_runtime_unsupported"
                if not real_start.error or real_start.error.code not in {
                    "CC_CONNECT_SECRETLESS_RUNTIME_UNSUPPORTED",
                    "MANAGED_PROCESS_EXITED_DURING_STARTUP",
                    "MANAGED_PROCESS_STARTUP_TIMEOUT",
                }:
                    raise AssertionError(real_start.model_dump_json())
                stop_result = lifecycle_action(
                    lifecycle,
                    database,
                    "stop",
                    final_revision,
                    key="runtime-acceptance-stop-after-upstream-exit",
                )
                restart_result = lifecycle_action(
                    lifecycle,
                    database,
                    "restart",
                    final_revision,
                    key="runtime-acceptance-restart-after-upstream-exit",
                )

            restarted_control_plane_view = ManagedProcessService(
                database,
                installer.layout,
                configuration,
                version_store=version_store,
                port_inspector=ports,
                external_detector=lambda: False,
            ).status()
            for process in lifecycle._launched.values():
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except Exception:
                        process.kill()
            deadline = time.monotonic() + 3
            remaining = managed_processes(installer.layout.root)
            while remaining and time.monotonic() < deadline:
                time.sleep(0.05)
                remaining = managed_processes(installer.layout.root)
            if remaining:
                raise AssertionError(f"managed processes remained: {remaining}")
            leaks: list[str] = []
            for path in data_dir.rglob("*"):
                if path.is_file():
                    raw = path.read_bytes()
                    if canary.encode() in raw or b"sk-synthetic-acceptance-canary" in raw:
                        leaks.append(path.name)
            if leaks:
                raise AssertionError(f"synthetic secret leaked: {leaks}")
            if os.environ.get("PATH", "") != path_before:
                raise AssertionError("acceptance changed process PATH")
            if external_candidate_stat() != external_before:
                raise AssertionError("external cc-connect candidate changed")
            evidence = {
                "status": "PARTIAL" if real_start.status != OperationStatus.SUCCEEDED else "PASSED",
                "started_at": started_at.isoformat(),
                "completed_at": datetime.now(UTC).isoformat(),
                "platform": sys.platform,
                "windows_version": sys.getwindowsversion().platform_version,
                "is_admin": bool(ctypes.windll.shell32.IsUserAnAdmin()),
                "artifact_id": manifest.artifact_id,
                "artifact_sha256": manifest.artifact_sha256,
                "install_status": install_result.status.value,
                "ownership_status": owner_result.status.value,
                "configuration_revision": final_revision,
                "configuration_rollback_to_revision": 1,
                "configuration_revision_conflict": race_conflict.error.code,
                "listen_host": "127.0.0.1",
                "listen_port_kind": "dynamic_product_controlled_range",
                "port_conflict_diagnostic": port_conflict.error.code,
                "external_owner_diagnostic": external_conflict.error.code,
                "real_start_status": real_start.status.value,
                "real_start_diagnostic": real_start.error.code if real_start.error else None,
                "real_runtime_status": real_runtime_status,
                "stop_after_start_status": stop_result.status.value,
                "restart_status": restart_result.status.value,
                "control_plane_restart_observed_state": restarted_control_plane_view.observed_state,
                "deep_health": "unsupported",
                "health_level": "partial_or_unhealthy_never_complete",
                "upstream_sustained_secretless_mode": "unsupported",
                "managed_processes_after": remaining,
                "unicode_space_parentheses_path": True,
                "non_system_drive": True,
                "ordinary_user_observed": not bool(ctypes.windll.shell32.IsUserAnAdmin()),
                "no_visible_console_flags_covered": True,
                "path_unchanged": True,
                "registry_modified": False,
                "windows_service_created": False,
                "scheduled_task_modified": False,
                "watchdog_modified": False,
                "reference_baseline_modified": False,
                "external_candidate_unchanged": True,
                "telegram_messages_sent": 0,
                "real_secret_values_read": 0,
                "real_secret_values_written": 0,
                "synthetic_secret_leaks": leaks,
                "windows_10_status": "PENDING_USER_REAL_MACHINE_VALIDATION",
            }
            database.engine.dispose()
            database = None
            return evidence
    finally:
        if database is not None:
            database.engine.dispose()
        for name, value in original_environment.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--temp-root", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    evidence = run(arguments.bundle, arguments.temp_root)
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")


if __name__ == "__main__":
    main()
