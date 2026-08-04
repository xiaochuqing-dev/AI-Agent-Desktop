from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal

import psutil

from ..configuration.models import LifecycleOwner
from ..installer.artifacts import InstallerError, sha256_file
from .models import IdentityVerification, ProcessIdentity


def _canonical_path(value: str | Path) -> str:
    resolved = str(Path(value).resolve(strict=False))
    return os.path.normcase(resolved)


def command_digest(arguments: Sequence[str]) -> str:
    normalized: list[str] = []
    for index, argument in enumerate(arguments):
        if index == 0 or (index > 0 and arguments[index - 1] in {"-config", "--config"}):
            normalized.append(_canonical_path(argument))
        else:
            normalized.append(argument)
    encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def format_create_time(value: float) -> str:
    return f"{value:.6f}"


class ProcessIdentityInspector:
    def __init__(self, process_factory: Callable[[int], Any] | None = None) -> None:
        self._process_factory = process_factory or psutil.Process

    def capture(
        self,
        *,
        pid: int,
        expected_executable: Path,
        expected_sha256: str,
        expected_arguments: Sequence[str],
        component_id: Literal["cc-connect"],
        product_instance_id: str,
        artifact_id: str,
        configuration_revision: int,
        listen_host: Literal["127.0.0.1"],
        listen_port: int,
        operation_id: str,
    ) -> ProcessIdentity:
        try:
            process = self._process_factory(pid)
            executable = Path(process.exe()).resolve(strict=True)
            create_time = float(process.create_time())
            parent_pid = int(process.ppid())
            arguments = [str(value) for value in process.cmdline()]
        except psutil.NoSuchProcess:
            raise InstallerError(
                "MANAGED_PROCESS_EXITED_DURING_IDENTITY_CAPTURE",
                "cc-connect exited before its process identity could be recorded.",
                retryable=True,
                recovery_actions=["inspect_startup_log", "retry_start"],
            ) from None
        except (OSError, psutil.AccessDenied):
            raise InstallerError(
                "MANAGED_PROCESS_IDENTITY_INACCESSIBLE",
                "Current user cannot inspect the launched process identity.",
                recovery_actions=["inspect_current_user_permissions"],
            ) from None
        actual_sha256 = sha256_file(executable)
        checks = {
            "executable_path": _canonical_path(executable) == _canonical_path(expected_executable),
            "executable_sha256": actual_sha256 == expected_sha256,
            "start_command_digest": command_digest(arguments) == command_digest(expected_arguments),
        }
        if not all(checks.values()):
            raise InstallerError(
                "MANAGED_PROCESS_IDENTITY_MISMATCH",
                "Launched process identity does not match the confirmed artifact and command.",
                recovery_actions=["stop_unverified_child_manually", "inspect_product_state"],
                technical_details=checks,
            )
        return ProcessIdentity(
            component_id=component_id,
            product_instance_id=product_instance_id,
            artifact_id=artifact_id,
            executable_path=str(executable),
            executable_sha256=actual_sha256,
            pid=pid,
            process_create_time=format_create_time(create_time),
            parent_pid=parent_pid,
            start_command_digest=command_digest(expected_arguments),
            configuration_revision=configuration_revision,
            listen_host=listen_host,
            listen_port=listen_port,
            lifecycle_owner=LifecycleOwner.PRODUCT,
            operation_id=operation_id,
        )

    def verify(self, identity: ProcessIdentity) -> IdentityVerification:
        try:
            process = self._process_factory(identity.pid)
            actual_create_time = format_create_time(float(process.create_time()))
        except psutil.NoSuchProcess:
            return IdentityVerification(status="missing", checks={"process_exists": False})
        except (OSError, psutil.AccessDenied):
            return IdentityVerification(
                status="inaccessible",
                checks={"process_exists": "unknown"},
                diagnostic_code="MANAGED_PROCESS_IDENTITY_INACCESSIBLE",
            )
        if actual_create_time != identity.process_create_time:
            return IdentityVerification(
                status="pid_reused",
                checks={
                    "process_exists": True,
                    "create_time": False,
                    "expected_create_time": identity.process_create_time,
                    "actual_create_time": actual_create_time,
                },
                diagnostic_code="MANAGED_PROCESS_PID_REUSED",
            )
        try:
            executable = Path(process.exe()).resolve(strict=True)
            actual_arguments = [str(value) for value in process.cmdline()]
            actual_parent = int(process.ppid())
            actual_sha256 = sha256_file(executable)
        except psutil.NoSuchProcess:
            return IdentityVerification(status="missing", checks={"process_exists": False})
        except (OSError, psutil.AccessDenied):
            return IdentityVerification(
                status="inaccessible",
                checks={"process_exists": True, "details_accessible": False},
                diagnostic_code="MANAGED_PROCESS_IDENTITY_INACCESSIBLE",
            )
        checks: dict[str, bool | str] = {
            "process_exists": True,
            "create_time": True,
            "executable_path": _canonical_path(executable)
            == _canonical_path(identity.executable_path),
            "executable_sha256": actual_sha256 == identity.executable_sha256,
            "parent_pid": actual_parent == identity.parent_pid,
            "start_command_digest": command_digest(actual_arguments)
            == identity.start_command_digest,
        }
        if all(value is True for value in checks.values()):
            return IdentityVerification(status="verified", checks=checks)
        if checks["executable_sha256"] is False:
            code = "MANAGED_PROCESS_EXECUTABLE_INTEGRITY_FAILURE"
        elif checks["executable_path"] is False:
            code = "MANAGED_PROCESS_EXECUTABLE_PATH_MISMATCH"
        elif checks["start_command_digest"] is False:
            code = "MANAGED_PROCESS_COMMAND_MISMATCH"
        else:
            code = "MANAGED_PROCESS_IDENTITY_MISMATCH"
        return IdentityVerification(status="mismatch", checks=checks, diagnostic_code=code)

    @staticmethod
    def external_candidate_detected(product_root: Path) -> bool:
        resolved_root = product_root.resolve(strict=False)
        for process in psutil.process_iter(["name", "exe"]):
            try:
                name = str(process.info.get("name") or "").casefold()
                executable = process.info.get("exe")
                if name not in {"cc-connect", "cc-connect.exe"} and not (
                    executable and Path(executable).name.casefold() == "cc-connect.exe"
                ):
                    continue
                if not executable:
                    return True
                if not Path(executable).resolve(strict=False).is_relative_to(resolved_root):
                    return True
            except (OSError, psutil.Error):
                return True
        return False
