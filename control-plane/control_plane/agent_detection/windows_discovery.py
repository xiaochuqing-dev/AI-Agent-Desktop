from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .models import DetectionSource


@dataclass(frozen=True)
class ExecutableCandidate:
    path: Path
    source: DetectionSource


class WindowsExecutableDiscovery:
    """Find supported CLI entrypoints without reading private configuration.

    PATH entries have precedence over documented per-user install locations. On
    Windows, App Execution Alias entries under WindowsApps are ignored because
    the placeholder can exist while the real CLI is unavailable.
    """

    def __init__(
        self,
        *,
        environ: Mapping[str, str] | None = None,
        path_lookup=shutil.which,
        platform_name: str | None = None,
    ) -> None:
        self.environ = dict(environ or os.environ)
        self.path_lookup = path_lookup
        self.platform_name = platform_name or sys.platform

    def discover(
        self,
        command_name: str,
        known_locations: Iterable[Path],
    ) -> list[ExecutableCandidate]:
        candidates: list[ExecutableCandidate] = []
        seen: set[str] = set()
        path_value = self.environ.get("PATH", "")

        separator = ";" if self.platform_name == "win32" else os.pathsep
        for raw_directory in path_value.split(separator):
            directory = raw_directory.strip().strip('"')
            if not directory:
                continue
            base = Path(os.path.expandvars(directory))
            for name in self._candidate_names(command_name):
                self._append(candidates, seen, base / name, DetectionSource.PATH)

        # Preserve PATH directory precedence across executable extensions. A
        # later ``agent.exe`` must not outrank an earlier ``agent.cmd`` wrapper.
        # ``shutil.which`` remains a fallback for platform-specific resolution
        # that the explicit scan may not cover.
        for name in self._candidate_names(command_name):
            try:
                resolved = self.path_lookup(name, path=path_value)
            except TypeError:
                resolved = self.path_lookup(name)
            except OSError:
                resolved = None
            if resolved:
                self._append(candidates, seen, Path(resolved), DetectionSource.PATH)

        for path in known_locations:
            self._append(candidates, seen, path, DetectionSource.KNOWN_LOCATION)
        return candidates

    def _candidate_names(self, command_name: str) -> tuple[str, ...]:
        if self.platform_name == "win32":
            return (
                f"{command_name}.exe",
                f"{command_name}.cmd",
                f"{command_name}.bat",
                command_name,
            )
        return (command_name,)

    def _append(
        self,
        candidates: list[ExecutableCandidate],
        seen: set[str],
        path: Path,
        source: DetectionSource,
    ) -> None:
        expanded = Path(os.path.expandvars(str(path))).expanduser()
        if self._is_windows_alias(expanded):
            return
        try:
            if not expanded.is_file():
                return
            canonical = expanded.resolve(strict=True)
        except OSError:
            return
        key = os.path.normcase(str(canonical)) if self.platform_name == "win32" else str(canonical)
        if key in seen:
            return
        seen.add(key)
        candidates.append(ExecutableCandidate(path=canonical, source=source))

    def _is_windows_alias(self, path: Path) -> bool:
        if self.platform_name != "win32":
            return False
        normalized = str(path).replace("/", "\\").casefold()
        return "\\microsoft\\windowsapps\\" in normalized or normalized.endswith(
            "\\microsoft\\windowsapps"
        )
