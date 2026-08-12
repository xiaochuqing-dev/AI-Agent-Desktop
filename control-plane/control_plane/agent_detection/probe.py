from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import ProbeStatus

CREATE_NO_WINDOW = 0x08000000
MAX_VERSION_OUTPUT_BYTES = 4096


@dataclass(frozen=True)
class VersionProbeResult:
    status: ProbeStatus
    version: str | None
    exit_code: int | None
    diagnostic_code: str | None
    output_truncated: bool = False


class VersionNormalizer:
    _version = re.compile(
        r"(?<![0-9A-Za-z])(?:v(?:ersion)?\s*)?"
        r"(?P<version>\d+(?:\.\d+){1,3}(?:[-+][0-9A-Za-z.-]+)?)",
        re.IGNORECASE,
    )

    @classmethod
    def normalize(cls, output: str) -> str | None:
        cleaned = " ".join(part.strip() for part in output.splitlines() if part.strip())
        match = cls._version.search(cleaned)
        if match is None:
            return None
        return match.group("version")[:128]


class SafeVersionProbe:
    """Run a detector-owned version command with a bounded, sanitized contract."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 4.0,
        max_output_bytes: int = MAX_VERSION_OUTPUT_BYTES,
        environ: Mapping[str, str] | None = None,
        runner=subprocess.run,
        platform_name: str | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.environ = dict(environ or os.environ)
        self.runner = runner
        self.platform_name = platform_name or sys.platform

    def probe(
        self,
        executable: Path,
        arguments: Sequence[str] = ("--version",),
    ) -> VersionProbeResult:
        environment = self._safe_environment(executable.parent)
        argv = self._argv(executable, arguments, environment)
        try:
            completed = self.runner(
                argv,
                cwd=str(executable.parent),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                check=False,
                text=False,
                timeout=self.timeout_seconds,
                creationflags=CREATE_NO_WINDOW if self.platform_name == "win32" else 0,
                close_fds=True,
            )
        except subprocess.TimeoutExpired:
            return VersionProbeResult(
                status=ProbeStatus.TIMEOUT,
                version=None,
                exit_code=None,
                diagnostic_code="AGENT_PROBE_TIMEOUT",
            )
        except (FileNotFoundError, PermissionError, OSError):
            return VersionProbeResult(
                status=ProbeStatus.LAUNCH_ERROR,
                version=None,
                exit_code=None,
                diagnostic_code="AGENT_PROBE_FAILED",
            )

        stdout = self._as_bytes(getattr(completed, "stdout", b""))
        stderr = self._as_bytes(getattr(completed, "stderr", b""))
        selected = stdout if stdout.strip() else stderr
        truncated = len(selected) > self.max_output_bytes
        decoded = selected[: self.max_output_bytes].decode("utf-8", errors="replace")
        exit_code = int(getattr(completed, "returncode", 1))
        if exit_code != 0:
            return VersionProbeResult(
                status=ProbeStatus.FAILED,
                version=None,
                exit_code=exit_code,
                diagnostic_code="AGENT_PROBE_FAILED",
                output_truncated=truncated,
            )
        version = VersionNormalizer.normalize(decoded)
        if version is None:
            return VersionProbeResult(
                status=ProbeStatus.VERSION_UNKNOWN,
                version=None,
                exit_code=exit_code,
                diagnostic_code="AGENT_VERSION_UNKNOWN",
                output_truncated=truncated,
            )
        return VersionProbeResult(
            status=ProbeStatus.HEALTHY,
            version=version,
            exit_code=exit_code,
            diagnostic_code=None,
            output_truncated=truncated,
        )

    def _argv(
        self,
        executable: Path,
        arguments: Sequence[str],
        environment: Mapping[str, str],
    ) -> list[str]:
        if self.platform_name == "win32" and executable.suffix.casefold() in {".cmd", ".bat"}:
            comspec = environment.get("COMSPEC") or "cmd.exe"
            command_line = subprocess.list2cmdline([str(executable), *arguments])
            return [comspec, "/d", "/s", "/c", command_line]
        return [str(executable), *arguments]

    def _safe_environment(self, executable_directory: Path) -> dict[str, str]:
        allowed = {
            "SYSTEMROOT",
            "WINDIR",
            "COMSPEC",
            "PATHEXT",
            "TEMP",
            "TMP",
            "LOCALAPPDATA",
            "APPDATA",
            "USERPROFILE",
            "HOMEDRIVE",
            "HOMEPATH",
            "LANG",
            "LC_ALL",
        }
        result = {name: value for name in allowed if (value := self.environ.get(name))}
        separator = ";" if self.platform_name == "win32" else os.pathsep
        inherited_path = self.environ.get("PATH", "")
        result["PATH"] = separator.join(
            part for part in (str(executable_directory), inherited_path) if part
        )
        return result

    @staticmethod
    def _as_bytes(value: Any) -> bytes:
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            return value.encode("utf-8", errors="replace")
        return b""
