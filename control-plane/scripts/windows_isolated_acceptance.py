"""Real Windows acceptance for the locked cc-connect artifact and isolated installer."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil

from control_plane.application.event_log import EventLog
from control_plane.application.operation_store import OperationStore
from control_plane.domain.models import OperationStatus
from control_plane.infrastructure.config import Settings, default_data_dir
from control_plane.installer.artifacts import InstallerError, load_manifest
from control_plane.installer.models import (
    InstallConfirmationRequest,
    InstallPlanRequest,
    RestoreRequest,
    UninstallRequest,
)
from control_plane.installer.service import CcConnectInstaller
from control_plane.persistence.models import ComponentVersionRecord
from control_plane.persistence.session import Database


def _operation(database: Database, operation_id: str):
    with database.session() as session:
        operation = OperationStore(session).get(operation_id)
    if operation is None:
        raise AssertionError(f"operation disappeared: {operation_id}")
    return operation


def _plan(installer: CcConnectInstaller, digest: str):
    return installer.create_plan(
        InstallPlanRequest(
            source_ref="trusted-local-bundle",
            expected_digest=f"sha256:{digest}",
        )
    )


def _confirm(installer: CcConnectInstaller, plan, key: str):
    confirmation = InstallConfirmationRequest(
        requested_version=plan.version,
        source_ref=plan.source.source_ref,
        expected_digest=f"sha256:{plan.sha256}",
        confirm=True,
        plan_id=plan.plan_id,
        plan_digest=plan.plan_digest,
        confirmation=True,
    )
    operation, reused = installer.confirm_install(
        confirmation,
        idempotency_key=key,
        body=confirmation.model_dump_json().encode(),
    )
    return operation, confirmation, reused


def _install(installer: CcConnectInstaller, database: Database, digest: str, key: str):
    plan = _plan(installer, digest)
    operation, confirmation, reused = _confirm(installer, plan, key)
    if reused:
        raise AssertionError("new acceptance operation unexpectedly reused")
    installer.execute_install(operation.operation_id, plan.plan_id, "windows-acceptance")
    completed = _operation(database, operation.operation_id)
    return plan, operation, confirmation, completed


def _add_synthetic_managed_copy(
    installer: CcConnectInstaller,
    database: Database,
    source: Path,
    artifact_id: str,
) -> None:
    manifest, _ = load_manifest(source / "cc-connect-artifact-manifest.json")
    copied_manifest = manifest.model_copy(update={"artifact_id": artifact_id})
    target = installer.layout.version_dir(artifact_id)
    target.mkdir(parents=True)
    shutil.copyfile(source / manifest.artifact_filename, target / manifest.artifact_filename)
    (target / "cc-connect-artifact-manifest.json").write_text(
        copied_manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    (target / "install-record.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "operation_id": f"acceptance-{artifact_id}",
                "component_id": "cc-connect",
                "artifact_id": artifact_id,
                "version": copied_manifest.version,
                "artifact_sha256": copied_manifest.artifact_sha256,
                "management_owner": "product",
                "lifecycle_takeover": False,
                "installed_at": datetime.now(UTC).isoformat(),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    with database.session() as session:
        session.add(
            ComponentVersionRecord(
                artifact_id=artifact_id,
                component_id="cc-connect",
                version=copied_manifest.version,
                relative_path=f"versions/{artifact_id}",
                artifact_sha256=copied_manifest.artifact_sha256,
                artifact_size=copied_manifest.artifact_size,
                status="installed",
                installed_at=datetime.now(UTC),
                removed_at=None,
            )
        )


def _lock_file_without_delete_sharing(path: Path) -> int:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    create_file.restype = ctypes.c_void_p
    handle = create_file(str(path), 0x80000000, 0x00000001, None, 3, 0x80, None)
    invalid = ctypes.c_void_p(-1).value
    if handle == invalid:
        raise OSError(ctypes.get_last_error(), "CreateFileW failed")
    return int(handle)


def _close_handle(handle: int) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    if not kernel32.CloseHandle(ctypes.c_void_p(handle)):
        raise OSError(ctypes.get_last_error(), "CloseHandle failed")


def _managed_processes(root: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    resolved = root.resolve(strict=False)
    for process in psutil.process_iter(["pid", "name", "exe"]):
        try:
            executable = process.info.get("exe")
            if executable and Path(executable).resolve().is_relative_to(resolved):
                result.append({"pid": process.pid, "name": process.info.get("name")})
        except (OSError, psutil.Error):
            continue
    return result


def _stat_external_candidate() -> dict[str, Any] | None:
    candidate = shutil.which("cc-connect") or shutil.which("cc-connect.exe")
    if not candidate:
        return None
    path = Path(candidate)
    stat = path.stat()
    return {"path": str(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _non_system_temp_root(explicit: Path | None = None) -> Path:
    system_drive = Path(os.environ.get("SystemDrive", "C:") + "\\").drive.casefold()
    candidates = (
        [explicit] if explicit else [Path(f"{letter}:\\") for letter in "DEFGHIJKLMNOPQRSTUVWXYZ"]
    )
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved.drive.casefold() != system_drive:
            return resolved
    raise RuntimeError("a writable non-system drive is required for Windows acceptance")


def run(bundle: Path, temp_root: Path | None = None) -> dict[str, Any]:
    if sys.platform != "win32":
        raise RuntimeError("Windows acceptance requires a Windows host")
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
        )
    }
    path_before = os.environ.get("PATH", "")
    external_before = _stat_external_candidate()
    canary = "123456789:AAAcceptanceCanary_NotARealTelegramToken_1234567890"
    database: Database | None = None
    evidence: dict[str, Any] = {}
    try:
        non_system_root = _non_system_temp_root(temp_root)
        with tempfile.TemporaryDirectory(
            prefix="AI Agent Desktop 隔离验收 (cc-connect) ", dir=non_system_root
        ) as root_name:
            root = Path(root_name)
            long_root = root
            local_name = "Local AppData 中文 (临时)"
            planned_artifact = (
                long_root
                / local_name
                / "AI-Agent-Desktop"
                / "components"
                / "cc-connect"
                / "versions"
                / manifest.artifact_id
                / manifest.artifact_filename
            )
            if len(str(planned_artifact)) < 225:
                segment_prefix = "long-path-中文-"
                padding = 225 - len(str(planned_artifact)) - len(segment_prefix) - 1
                long_root /= segment_prefix + ("x" * padding)
                planned_artifact = (
                    long_root
                    / local_name
                    / "AI-Agent-Desktop"
                    / "components"
                    / "cc-connect"
                    / "versions"
                    / manifest.artifact_id
                    / manifest.artifact_filename
                )
            local_app_data = long_root / local_name
            isolated_profile = root / "User Profile 中文 (临时)"
            local_app_data.mkdir(parents=True)
            isolated_profile.mkdir(parents=True)
            os.environ["LOCALAPPDATA"] = str(local_app_data)
            os.environ["APPDATA"] = str(isolated_profile / "AppData" / "Roaming")
            os.environ["HOME"] = str(isolated_profile)
            os.environ["USERPROFILE"] = str(isolated_profile)
            # platformdirs exposes these Windows overrides for portable/test roots.
            os.environ["WIN_PD_OVERRIDE_LOCAL_APPDATA"] = str(local_app_data)
            os.environ["WIN_PD_OVERRIDE_APPDATA"] = str(isolated_profile / "AppData" / "Roaming")
            os.environ["TELEGRAM_BOT_TOKEN"] = canary
            data_dir = Path(default_data_dir())
            if not data_dir.resolve(strict=False).is_relative_to(local_app_data.resolve()):
                raise AssertionError("platformdirs did not resolve inside temporary LocalAppData")
            if len(str(planned_artifact)) < 220 or len(str(planned_artifact)) >= 250:
                raise AssertionError("acceptance did not exercise a safe near-MAX_PATH layout")
            settings = Settings(data_dir=str(data_dir), trusted_artifact_dir=str(bundle))
            database = Database(settings)
            installer = CcConnectInstaller(settings, database, EventLog())

            rollback_plan = _plan(installer, manifest.artifact_sha256)
            rollback_operation, _, _ = _confirm(
                installer, rollback_plan, "acceptance-rollback-0001"
            )
            original_record = installer._record_install_success

            def fail_after_activation(*_args, **_kwargs) -> None:
                raise InstallerError(
                    "ACCEPTANCE_POST_ACTIVATION_FAILURE", "Injected acceptance failure"
                )

            installer._record_install_success = fail_after_activation  # type: ignore[method-assign]
            installer.execute_install(
                rollback_operation.operation_id,
                rollback_plan.plan_id,
                "windows-acceptance",
            )
            installer._record_install_success = original_record  # type: ignore[method-assign]
            rollback_result = _operation(database, rollback_operation.operation_id)
            if rollback_result.progress.phase != "rolled_back" or installer.layout.read_current():
                raise AssertionError("post-activation failure did not roll back cleanly")

            plan, operation, confirmation, completed = _install(
                installer,
                database,
                manifest.artifact_sha256,
                "acceptance-install-0001",
            )
            if completed.status != OperationStatus.SUCCEEDED:
                raise AssertionError(completed.model_dump_json())
            retry, reused = installer.confirm_install(
                confirmation,
                idempotency_key="acceptance-install-0001",
                body=confirmation.model_dump_json().encode(),
            )
            if not reused or retry.operation_id != operation.operation_id:
                raise AssertionError("idempotency retry did not return the original operation")
            duplicate_plan, duplicate_operation, _, duplicate = _install(
                installer,
                database,
                manifest.artifact_sha256,
                "acceptance-install-0002",
            )
            if not duplicate.result or not duplicate.result.get("already_installed"):
                raise AssertionError("same artifact install was not a no-op")

            previous_id = "cc-connect-acceptance-previous"
            _add_synthetic_managed_copy(installer, database, bundle, previous_id)
            current = installer.layout.read_current()
            if current is None:
                raise AssertionError("current pointer missing after install")
            current["previous_artifact_id"] = previous_id
            installer.layout.write_current(current)
            restore_request = RestoreRequest(confirm=True)
            restore_operation, _ = installer.create_restore_operation(
                restore_request,
                idempotency_key="acceptance-restore-0001",
                body=restore_request.model_dump_json().encode(),
            )
            installer.execute_restore(
                restore_operation.operation_id, restore_request, "windows-acceptance"
            )
            restored = _operation(database, restore_operation.operation_id)
            if restored.status != OperationStatus.SUCCEEDED:
                raise AssertionError(restored.model_dump_json())

            uninstall = UninstallRequest(artifact_id=manifest.artifact_id, confirm=True)
            uninstall_operation, _ = installer.create_uninstall_operation(
                uninstall,
                idempotency_key="acceptance-uninstall-0001",
                body=uninstall.model_dump_json().encode(),
            )
            installer.execute_uninstall(
                uninstall_operation.operation_id, uninstall, "windows-acceptance"
            )
            uninstalled = _operation(database, uninstall_operation.operation_id)
            if uninstalled.status != OperationStatus.SUCCEEDED:
                raise AssertionError(uninstalled.model_dump_json())

            reject_current = UninstallRequest(artifact_id=previous_id, confirm=True)
            reject_operation, _ = installer.create_uninstall_operation(
                reject_current,
                idempotency_key="acceptance-uninstall-current",
                body=reject_current.model_dump_json().encode(),
            )
            installer.execute_uninstall(
                reject_operation.operation_id, reject_current, "windows-acceptance"
            )
            rejected = _operation(database, reject_operation.operation_id)
            if not rejected.error or rejected.error.code != "CURRENT_VERSION_IN_USE":
                raise AssertionError("current version uninstall was not rejected")

            locked_id = "cc-connect-acceptance-locked-copy"
            _add_synthetic_managed_copy(installer, database, bundle, locked_id)
            locked_target = installer.layout.version_dir(locked_id)
            handle = _lock_file_without_delete_sharing(locked_target / "cc-connect.exe")
            try:
                locked_request = UninstallRequest(artifact_id=locked_id, confirm=True)
                locked_operation, _ = installer.create_uninstall_operation(
                    locked_request,
                    idempotency_key="acceptance-pending-cleanup",
                    body=locked_request.model_dump_json().encode(),
                )
                installer.execute_uninstall(
                    locked_operation.operation_id, locked_request, "windows-acceptance"
                )
                locked_result = _operation(database, locked_operation.operation_id)
                if locked_result.progress.phase != "pending_cleanup":
                    raise AssertionError("locked file was not recorded as pending cleanup")
            finally:
                _close_handle(handle)
            if installer.retry_pending_cleanup() != 1 or locked_target.exists():
                raise AssertionError("pending cleanup retry did not remove the unlocked version")

            if os.environ.get("PATH", "") != path_before:
                raise AssertionError("acceptance changed PATH")
            managed_processes = _managed_processes(data_dir)
            deadline = time.monotonic() + 2
            while managed_processes and time.monotonic() < deadline:
                time.sleep(0.05)
                managed_processes = _managed_processes(data_dir)
            if managed_processes:
                raise AssertionError(f"managed process remained: {managed_processes}")
            leaked_files = []
            canary_bytes = canary.encode()
            for path in data_dir.rglob("*"):
                if path.is_file() and canary_bytes in path.read_bytes():
                    leaked_files.append(str(path.relative_to(data_dir)))
            if leaked_files:
                raise AssertionError(f"synthetic secret leaked: {leaked_files}")
            external_after = _stat_external_candidate()
            if external_after != external_before:
                raise AssertionError("external cc-connect candidate changed during acceptance")

            evidence = {
                "status": "passed",
                "started_at": started_at.isoformat(),
                "completed_at": datetime.now(UTC).isoformat(),
                "platform": sys.platform,
                "windows_version": sys.getwindowsversion().platform_version,
                "is_admin": bool(ctypes.windll.shell32.IsUserAnAdmin()),
                "artifact_id": manifest.artifact_id,
                "artifact_sha256": manifest.artifact_sha256,
                "data_dir_kind": "temporary-platformdirs-localappdata",
                "data_dir_length": len(str(data_dir)),
                "managed_artifact_path_length": len(str(planned_artifact)),
                "non_system_drive": data_dir.drive.casefold()
                != Path(os.environ.get("SystemDrive", "C:") + "\\").drive.casefold(),
                "unicode_space_parentheses_path": True,
                "rollback_phase": rollback_result.progress.phase,
                "install_status": completed.status.value,
                "duplicate_plan_id": duplicate_plan.plan_id,
                "duplicate_operation_id": duplicate_operation.operation_id,
                "idempotency_reused": reused,
                "restore_status": restored.status.value,
                "uninstall_status": uninstalled.status.value,
                "current_uninstall_error": rejected.error.code if rejected.error else None,
                "pending_cleanup_retried": True,
                "managed_processes_after": managed_processes,
                "path_unchanged": True,
                "external_candidate_unchanged": True,
                "synthetic_secret_leaks": leaked_files,
                "health_probe": "version_only_offline",
                "deep_health": "unsupported",
                "telegram_messages_sent": 0,
                "real_user_configuration_written": False,
            }
            database.engine.dispose()
            database = None
    finally:
        if database is not None:
            database.engine.dispose()
        for name, value in original_environment.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--temp-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    evidence = run(args.bundle, args.temp_root)
    output = json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    print(output, end="")


if __name__ == "__main__":
    main()
