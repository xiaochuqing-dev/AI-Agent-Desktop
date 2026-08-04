from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import psutil
from pydantic import BaseModel, ConfigDict, Field

from ..lifecycle.port_ownership import PortOwnershipInspector


class ExternalCcConnectState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_installed: bool | Literal["unknown"]
    external_process_running: bool | Literal["unknown"]
    external_port_active: bool | Literal["unknown"]
    external_supervisor_detected: bool | Literal["unknown"]
    external_configuration_detected: bool | Literal["unknown"]
    external_owner_known: bool | Literal["unknown"]
    conflict: bool
    unknown: bool
    evidence: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class ProcessObservation:
    pid: int
    executable: str | None
    command_line: list[str] | None
    accessible: bool


ProcessProvider = Callable[[], list[ProcessObservation]]
SupervisorProbe = Callable[[], bool | Literal["unknown"]]


class CcConnectExternalDetector:
    def __init__(
        self,
        product_root: Path,
        *,
        process_provider: ProcessProvider | None = None,
        port_inspector: PortOwnershipInspector | None = None,
        path_lookup: Callable[[str], str | None] | None = None,
        supervisor_probe: SupervisorProbe | None = None,
    ) -> None:
        self.product_root = product_root.resolve(strict=False)
        self.process_provider = process_provider or self._processes
        self.port_inspector = port_inspector or PortOwnershipInspector()
        self.path_lookup = path_lookup or shutil.which
        self.supervisor_probe = supervisor_probe or self._supervisor_probe

    def detect(
        self,
        *,
        target_port: int | None = None,
        target_config_path: Path | None = None,
    ) -> ExternalCcConnectState:
        candidate = self.path_lookup("cc-connect.exe") or self.path_lookup("cc-connect")
        installed: bool | Literal["unknown"] = False
        installed_path: str | None = None
        if candidate:
            try:
                resolved = Path(candidate).resolve(strict=False)
                if not resolved.is_relative_to(self.product_root):
                    installed = True
                    installed_path = str(resolved)
            except OSError:
                installed = "unknown"

        external_running: bool | Literal["unknown"] = False
        external_configuration: bool | Literal["unknown"] = False
        owner_known: bool | Literal["unknown"] = False
        external_pids: list[int] = []
        inaccessible_seen = False
        normalized_target_config = (
            os.path.normcase(str(target_config_path.resolve(strict=False)))
            if target_config_path is not None
            else None
        )
        observations = self.process_provider()
        product_pids: set[int] = set()
        for observation in observations:
            if not observation.accessible:
                inaccessible_seen = True
                continue
            executable = observation.executable or ""
            command_line = observation.command_line or []
            name_candidates = [
                Path(executable).name.casefold(),
                *(Path(arg).name.casefold() for arg in command_line[:1]),
            ]
            if not any(name in {"cc-connect", "cc-connect.exe"} for name in name_candidates):
                continue
            if executable:
                try:
                    if Path(executable).resolve(strict=False).is_relative_to(self.product_root):
                        product_pids.add(observation.pid)
                        continue
                except OSError:
                    inaccessible_seen = True
                    continue
            external_running = True
            owner_known = True
            external_pids.append(observation.pid)
            config_argument = self._config_argument(command_line)
            if config_argument is not None:
                try:
                    normalized = os.path.normcase(str(Path(config_argument).resolve(strict=False)))
                    if (
                        normalized_target_config is not None
                        and normalized == normalized_target_config
                    ):
                        external_configuration = True
                except OSError:
                    external_configuration = "unknown"

        if external_running is False and inaccessible_seen:
            external_running = "unknown"
            owner_known = "unknown"
        if external_configuration is False and inaccessible_seen:
            external_configuration = "unknown"

        external_port: bool | Literal["unknown"] = False
        port_owner_pid: int | None = None
        if target_port is not None:
            evidence = self.port_inspector.inspect("127.0.0.1", target_port)
            port_owner_pid = evidence.owner_pid
            if evidence.status == "unknown":
                external_port = "unknown"
            elif evidence.status in {"owned", "conflict"}:
                external_port = (
                    True if evidence.owner_pid is None else evidence.owner_pid not in product_pids
                )

        supervisor = self.supervisor_probe()
        conflict = bool(
            external_port is True or external_configuration is True or supervisor is True
        )
        unknown = any(
            item == "unknown"
            for item in (
                installed,
                external_running,
                external_port,
                supervisor,
                external_configuration,
                owner_known,
            )
        )
        return ExternalCcConnectState(
            external_installed=installed,
            external_process_running=external_running,
            external_port_active=external_port,
            external_supervisor_detected=supervisor,
            external_configuration_detected=external_configuration,
            external_owner_known=owner_known,
            conflict=conflict,
            unknown=unknown,
            evidence={
                "external_executable_path_present": bool(installed_path),
                "external_process_pids": external_pids,
                "target_port": target_port,
                "target_port_owner_pid": port_owner_pid,
                "path_installation_alone_blocks": False,
            },
        )

    def conflict(
        self,
        *,
        target_port: int | None = None,
        target_config_path: Path | None = None,
    ) -> bool:
        return self.detect(target_port=target_port, target_config_path=target_config_path).conflict

    def _inside_product(self, executable: str) -> bool:
        try:
            return Path(executable).resolve(strict=False).is_relative_to(self.product_root)
        except OSError:
            return False

    @staticmethod
    def _config_argument(command_line: list[str]) -> str | None:
        for index, value in enumerate(command_line):
            if value in {"-config", "--config"} and index + 1 < len(command_line):
                return command_line[index + 1]
            if value.startswith("-config=") or value.startswith("--config="):
                return value.split("=", 1)[1]
        return None

    @staticmethod
    def _processes() -> list[ProcessObservation]:
        observations: list[ProcessObservation] = []
        for process in psutil.process_iter(["pid", "exe", "cmdline", "name"]):
            try:
                observations.append(
                    ProcessObservation(
                        pid=int(process.info["pid"]),
                        executable=process.info.get("exe") or process.info.get("name"),
                        command_line=list(process.info.get("cmdline") or []),
                        accessible=True,
                    )
                )
            except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
                observations.append(
                    ProcessObservation(
                        pid=int(process.info.get("pid") or 0),
                        executable=None,
                        command_line=None,
                        accessible=False,
                    )
                )
        return observations

    @staticmethod
    def _supervisor_probe() -> bool | Literal["unknown"]:
        if sys.platform != "win32":
            return False
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            result = subprocess.run(
                ["schtasks.exe", "/Query", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                creationflags=creationflags,
            )
        except (OSError, subprocess.TimeoutExpired):
            return "unknown"
        if result.returncode != 0:
            return "unknown"
        return any(
            "cc-connect" in line.casefold() or "cc_connect" in line.casefold()
            for line in result.stdout.splitlines()
        )
