from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..installer.artifacts import InstallerError
from ..persistence.models import ExternalToolCapabilityRecord
from ..persistence.session import Database
from .models import ExternalToolCapability, ExternalToolStatus


class CcSwitchExternalToolProvider:
    provider_id = "cc-switch-external"

    def __init__(
        self,
        database: Database,
        *,
        launcher: Callable[..., Any] | None = None,
        candidates: list[Path] | None = None,
    ) -> None:
        self.db = database
        self.launcher = launcher or subprocess.Popen
        self.candidates = candidates

    def detect(self) -> ExternalToolStatus:
        candidate = self._find_executable()
        installed = candidate is not None
        now = datetime.now(UTC)
        capabilities = [
            ExternalToolCapability(
                capability="detection",
                status="supported",
                evidence="Executable-only detection; no private configuration or secret was read.",
            ),
            ExternalToolCapability(
                capability="launch",
                status="supported" if installed else "unavailable",
                evidence="Normal process launch is available only when an executable is detected.",
            ),
            ExternalToolCapability(
                capability="supported_agents",
                status="unknown",
                evidence="No stable public machine-readable capability API was verified.",
            ),
            ExternalToolCapability(
                capability="install",
                status="unknown",
                evidence="No stable public external install API or CLI was verified.",
            ),
            ExternalToolCapability(
                capability="update",
                status="unknown",
                evidence="No stable public external update API or CLI was verified.",
            ),
            ExternalToolCapability(
                capability="configuration",
                status="unknown",
                evidence="Deep-link import requires UI confirmation and is not treated as a write API.",
            ),
            ExternalToolCapability(
                capability="ownership_handoff",
                status="unknown",
                evidence="No public atomic ownership handoff protocol was verified.",
            ),
        ]
        status = ExternalToolStatus(
            provider_id=self.provider_id,
            display_name="CC Switch",
            installation_status="installed" if installed else "not_installed",
            executable_path=str(candidate) if candidate else None,
            version=None,
            capabilities=capabilities,
            last_verified_at=now,
            evidence={
                "probe": "known executable locations and PATH",
                "private_configuration_read": False,
                "secret_read": False,
                "source_modified": False,
            },
        )
        with self.db.session() as session:
            session.merge(
                ExternalToolCapabilityRecord(
                    provider_id=self.provider_id,
                    version=None,
                    status=status.installation_status,
                    capabilities_json=json.dumps(
                        [item.model_dump(mode="json") for item in capabilities], sort_keys=True
                    ),
                    evidence_json=json.dumps(status.evidence, sort_keys=True),
                    last_verified_at=now,
                    updated_at=now,
                )
            )
        return status

    def launch(self) -> dict[str, Any]:
        status = self.detect()
        if status.installation_status != "installed" or not status.executable_path:
            raise InstallerError(
                "CC_SWITCH_NOT_INSTALLED",
                "CC Switch executable was not detected; nothing was launched.",
                recovery_actions=["install_cc_switch_separately"],
            )
        try:
            process = self.launcher(
                [status.executable_path],
                cwd=str(Path(status.executable_path).parent),
                shell=False,
                close_fds=True,
            )
        except OSError as exc:
            raise InstallerError(
                "CC_SWITCH_LAUNCH_FAILED",
                "CC Switch could not be opened through its normal executable entrypoint.",
                retryable=True,
                recovery_actions=["open_cc_switch_manually"],
                technical_details={"error": type(exc).__name__},
            ) from None
        return {
            "provider_id": self.provider_id,
            "launched": True,
            "pid": int(process.pid),
            "configuration_written": False,
            "gui_automation_used": False,
        }

    def _find_executable(self) -> Path | None:
        if self.candidates is not None:
            candidates = self.candidates
        else:
            local = os.environ.get("LOCALAPPDATA")
            program_files = os.environ.get("ProgramFiles")
            candidates = []
            if local:
                candidates.extend(
                    [
                        Path(local) / "Programs" / "CC Switch" / "CC Switch.exe",
                        Path(local) / "Programs" / "cc-switch" / "CCSwitch.exe",
                        Path(local) / "CCSwitch" / "CCSwitch.exe",
                    ]
                )
            if program_files:
                candidates.extend(
                    [
                        Path(program_files) / "CC Switch" / "CC Switch.exe",
                        Path(program_files) / "CCSwitch" / "CCSwitch.exe",
                    ]
                )
            path_candidate = shutil.which("CCSwitch") or shutil.which("cc-switch")
            if path_candidate:
                candidates.append(Path(path_candidate))
        for candidate in candidates:
            try:
                if candidate.is_file():
                    return candidate.resolve(strict=True)
            except OSError:
                continue
        return None
