from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

from .models import (
    AgentDetectionResult,
    AgentId,
    DetectionSource,
    DetectionStatus,
    ProbeStatus,
)
from .probe import SafeVersionProbe
from .windows_discovery import WindowsExecutableDiscovery


class AgentDetector(Protocol):
    agent_id: AgentId

    def detect(self) -> AgentDetectionResult: ...


class BaseCliDetector:
    agent_id: AgentId
    display_name: str
    command_name: str
    official_install_url: str

    def __init__(
        self,
        *,
        discovery: WindowsExecutableDiscovery | None = None,
        probe: SafeVersionProbe | None = None,
        environ: Mapping[str, str] | None = None,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self.environ = dict(environ or os.environ)
        self.discovery = discovery or WindowsExecutableDiscovery(environ=self.environ)
        self.probe = probe or SafeVersionProbe(environ=self.environ)
        self.clock = clock

    def known_locations(self) -> Sequence[Path]:
        raise NotImplementedError

    def detect(self) -> AgentDetectionResult:
        observed = self.clock()
        try:
            candidates = self.discovery.discover(self.command_name, self.known_locations())
        except Exception:
            return self._result(
                observed=observed,
                status=DetectionStatus.DETECTION_ERROR,
                installed=None,
                source=DetectionSource.ERROR,
                probe_status=ProbeStatus.NOT_RUN,
                diagnostic_code="AGENT_DETECTION_ERROR",
                user_message=f"暂时无法检测 {self.display_name}。",
            )
        if not candidates:
            return self._result(
                observed=observed,
                status=DetectionStatus.NOT_FOUND,
                installed=False,
                source=DetectionSource.NOT_FOUND,
                probe_status=ProbeStatus.NOT_RUN,
                diagnostic_code="AGENT_NOT_FOUND",
                user_message=f"没有检测到 {self.display_name}。",
            )

        # The first supported entry is the user's effective installation. If it
        # is broken, do not hide that fact by reporting an older fallback copy.
        candidate = candidates[0]
        probe = self.probe.probe(candidate.path, ("--version",))
        if probe.status == ProbeStatus.HEALTHY:
            return self._result(
                observed=observed,
                status=DetectionStatus.INSTALLED,
                installed=True,
                version=probe.version,
                executable=candidate.path,
                source=candidate.source,
                probe_status=probe.status,
                exit_code=probe.exit_code,
                user_message=f"已检测到 {self.display_name}，版本 {probe.version}。",
            )
        if probe.status == ProbeStatus.VERSION_UNKNOWN:
            return self._result(
                observed=observed,
                status=DetectionStatus.VERSION_UNKNOWN,
                installed=True,
                executable=candidate.path,
                source=candidate.source,
                probe_status=probe.status,
                exit_code=probe.exit_code,
                diagnostic_code=probe.diagnostic_code,
                user_message=f"已检测到 {self.display_name}，但版本暂时无法识别。",
            )
        message = (
            f"{self.display_name} 版本检测超时。"
            if probe.status == ProbeStatus.TIMEOUT
            else f"已找到 {self.display_name}，但当前入口无法正常运行。"
        )
        return self._result(
            observed=observed,
            status=DetectionStatus.FOUND_BUT_UNHEALTHY,
            installed=True,
            executable=candidate.path,
            source=candidate.source,
            probe_status=probe.status,
            exit_code=probe.exit_code,
            diagnostic_code=probe.diagnostic_code,
            user_message=message,
        )

    def _result(
        self,
        *,
        observed: datetime,
        status: DetectionStatus,
        installed: bool | None,
        source: DetectionSource,
        probe_status: ProbeStatus,
        user_message: str,
        version: str | None = None,
        executable: Path | None = None,
        exit_code: int | None = None,
        diagnostic_code: str | None = None,
    ) -> AgentDetectionResult:
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "agent_id": self.agent_id,
                    "status": status.value,
                    "version": version,
                    "path": os.path.normcase(str(executable)) if executable else None,
                    "source": source.value,
                    "probe_status": probe_status.value,
                    "exit_code": exit_code,
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return AgentDetectionResult(
            agent_id=self.agent_id,
            display_name=self.display_name,
            status=status,
            installed=installed,
            version=version,
            executable_path_internal=str(executable) if executable else None,
            detection_source=source,
            probe_status=probe_status,
            probe_exit_code=exit_code,
            observed_at=observed,
            diagnostic_code=diagnostic_code,
            user_message=user_message,
            official_install_url=self.official_install_url,
            revision=f"sha256:{fingerprint}",
        )

    def _path(self, variable: str, *parts: str) -> Path | None:
        root = self.environ.get(variable)
        return Path(root, *parts) if root else None

    @staticmethod
    def _present(paths: Sequence[Path | None]) -> tuple[Path, ...]:
        return tuple(cast(Path, path) for path in paths if path is not None)


class HermesDetector(BaseCliDetector):
    agent_id: AgentId = "hermes"
    display_name = "Hermes"
    command_name = "hermes"
    official_install_url = "https://hermes-agent.nousresearch.com/docs/getting-started/installation"

    def known_locations(self) -> Sequence[Path]:
        # Current official launcher first, followed by the legacy venv entrypoint.
        return self._present(
            (
                self._path("LOCALAPPDATA", "hermes", "hermes-agent", "bin", "hermes.exe"),
                self._path(
                    "LOCALAPPDATA",
                    "hermes",
                    "hermes-agent",
                    "venv",
                    "Scripts",
                    "hermes.exe",
                ),
                self._path("LOCALAPPDATA", "hermes", "hermes-agent", "hermes.exe"),
            )
        )


class ClaudeCodeDetector(BaseCliDetector):
    agent_id: AgentId = "claude"
    display_name = "Claude Code"
    command_name = "claude"
    official_install_url = "https://docs.anthropic.com/en/docs/claude-code/setup"

    def known_locations(self) -> Sequence[Path]:
        return self._present(
            (
                self._path("USERPROFILE", ".local", "bin", "claude.exe"),
                self._path("USERPROFILE", ".local", "bin", "claude.cmd"),
                self._path("APPDATA", "npm", "claude.cmd"),
                self._path("APPDATA", "npm", "claude.exe"),
            )
        )


class CodexDetector(BaseCliDetector):
    agent_id: AgentId = "codex"
    display_name = "Codex"
    command_name = "codex"
    official_install_url = "https://developers.openai.com/codex/cli/"

    def known_locations(self) -> Sequence[Path]:
        return self._present(
            (
                self._path("LOCALAPPDATA", "Programs", "OpenAI", "Codex", "bin", "codex.exe"),
                self._path("APPDATA", "npm", "codex.cmd"),
                self._path("APPDATA", "npm", "codex.exe"),
                self._path("USERPROFILE", ".local", "bin", "codex.exe"),
            )
        )
