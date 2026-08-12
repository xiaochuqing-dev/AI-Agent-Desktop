from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from control_plane.agent_detection.detectors import ClaudeCodeDetector
from control_plane.agent_detection.models import (
    AgentDetectionResult,
    DetectionSource,
    DetectionStatus,
    ProbeStatus,
)
from control_plane.agent_detection.probe import CREATE_NO_WINDOW, SafeVersionProbe
from control_plane.agent_detection.service import AgentDetectionService
from control_plane.agent_detection.windows_discovery import WindowsExecutableDiscovery


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"synthetic executable")
    return path


def test_windows_discovery_path_precedes_known_location_and_supports_unicode(tmp_path):
    path_entry = tmp_path / "PATH 空格" / "claude.cmd"
    known = tmp_path / "已知位置" / "claude.exe"
    _touch(path_entry)
    _touch(known)
    discovery = WindowsExecutableDiscovery(
        environ={"PATH": str(path_entry.parent)},
        path_lookup=lambda _name, **_kwargs: None,
        platform_name="win32",
    )
    candidates = discovery.discover("claude", [known])
    assert [item.path for item in candidates] == [path_entry.resolve(), known.resolve()]
    assert [item.source for item in candidates] == [
        DetectionSource.PATH,
        DetectionSource.KNOWN_LOCATION,
    ]


def test_windows_discovery_preserves_directory_order_across_extensions(tmp_path):
    earlier_wrapper = _touch(tmp_path / "first" / "codex.cmd")
    later_executable = _touch(tmp_path / "second" / "codex.exe")
    discovery = WindowsExecutableDiscovery(
        environ={"PATH": f"{earlier_wrapper.parent};{later_executable.parent}"},
        path_lookup=lambda name, **_kwargs: str(later_executable) if name == "codex.exe" else None,
        platform_name="win32",
    )

    candidates = discovery.discover("codex", [])

    assert [item.path for item in candidates] == [
        earlier_wrapper.resolve(),
        later_executable.resolve(),
    ]


def test_windows_discovery_excludes_windowsapps_alias(tmp_path):
    alias = _touch(tmp_path / "Microsoft" / "WindowsApps" / "codex.exe")
    discovery = WindowsExecutableDiscovery(
        environ={"PATH": str(alias.parent)},
        path_lookup=lambda _name, **_kwargs: str(alias),
        platform_name="win32",
    )
    assert discovery.discover("codex", []) == []


@pytest.mark.parametrize(
    ("stdout", "stderr", "returncode", "expected_status", "expected_version"),
    [
        (b"claude 2.8.1\n", b"", 0, ProbeStatus.HEALTHY, "2.8.1"),
        (b"", b"codex-cli 1.42.0-beta.2\n", 0, ProbeStatus.HEALTHY, "1.42.0-beta.2"),
        (b"new wrapper output", b"", 0, ProbeStatus.VERSION_UNKNOWN, None),
        (b"", b"runtime error", 1, ProbeStatus.FAILED, None),
        (b"Hermes version 2030.12.9+build.7", b"", 0, ProbeStatus.HEALTHY, "2030.12.9+build.7"),
    ],
)
def test_safe_probe_version_outcomes(
    tmp_path, stdout, stderr, returncode, expected_status, expected_version
):
    executable = _touch(tmp_path / "Agent Path" / "agent.exe")
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)

    result = SafeVersionProbe(runner=runner, platform_name="win32").probe(executable)
    assert result.status == expected_status
    assert result.version == expected_version
    argv, kwargs = calls[0]
    assert argv == [str(executable), "--version"]
    assert kwargs["shell"] is False
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["creationflags"] == CREATE_NO_WINDOW
    assert "OPENAI_API_KEY" not in kwargs["env"]
    assert "ANTHROPIC_API_KEY" not in kwargs["env"]


def test_safe_probe_cmd_wrapper_is_quoted_and_never_uses_shell(tmp_path):
    executable = _touch(tmp_path / "路径 含空格" / "claude.cmd")
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(stdout=b"claude 3.0.0", stderr=b"", returncode=0)

    result = SafeVersionProbe(
        runner=runner,
        platform_name="win32",
        environ={"COMSPEC": "C:/Windows/System32/cmd.exe", "PATH": "C:/Windows/System32"},
    ).probe(executable)
    assert result.version == "3.0.0"
    argv, kwargs = calls[0]
    assert argv[:4] == ["C:/Windows/System32/cmd.exe", "/d", "/s", "/c"]
    assert str(executable) in argv[4]
    assert kwargs["shell"] is False


def test_safe_probe_timeout_launch_failure_and_output_bound(tmp_path):
    executable = _touch(tmp_path / "agent.exe")

    def timeout_runner(*_args, **_kwargs):
        raise subprocess.TimeoutExpired([str(executable)], 1)

    timeout = SafeVersionProbe(runner=timeout_runner).probe(executable)
    assert timeout.status == ProbeStatus.TIMEOUT
    assert timeout.diagnostic_code == "AGENT_PROBE_TIMEOUT"

    def denied_runner(*_args, **_kwargs):
        raise PermissionError

    denied = SafeVersionProbe(runner=denied_runner).probe(executable)
    assert denied.status == ProbeStatus.LAUNCH_ERROR
    assert denied.diagnostic_code == "AGENT_PROBE_FAILED"

    huge = b"agent 9.8.7 " + b"x" * 10000
    bounded = SafeVersionProbe(
        runner=lambda *_args, **_kwargs: SimpleNamespace(stdout=huge, stderr=b"", returncode=0),
        max_output_bytes=32,
    ).probe(executable)
    assert bounded.version == "9.8.7"
    assert bounded.output_truncated is True


def test_detector_does_not_hide_broken_default_with_older_fallback(tmp_path):
    primary = _touch(tmp_path / "primary" / "claude.exe")
    fallback = _touch(tmp_path / "fallback" / "claude.exe")

    class Discovery:
        def discover(self, _command, _known):
            from control_plane.agent_detection.windows_discovery import ExecutableCandidate

            return [
                ExecutableCandidate(primary, DetectionSource.PATH),
                ExecutableCandidate(fallback, DetectionSource.KNOWN_LOCATION),
            ]

    class Probe:
        def probe(self, executable, _arguments):
            from control_plane.agent_detection.probe import VersionProbeResult

            assert executable == primary
            return VersionProbeResult(
                status=ProbeStatus.FAILED,
                version=None,
                exit_code=1,
                diagnostic_code="AGENT_PROBE_FAILED",
            )

    result = ClaudeCodeDetector(discovery=Discovery(), probe=Probe()).detect()  # type: ignore[arg-type]
    assert result.status == DetectionStatus.FOUND_BUT_UNHEALTHY
    assert result.installed is True
    assert result.executable_path_internal == str(primary)


def test_detection_service_ttl_and_explicit_refresh_change_result():
    now = [0.0]

    class Detector:
        def __init__(self, slot):
            self.agent_id = slot
            self.calls = 0

        def detect(self):
            self.calls += 1
            return AgentDetectionResult(
                agent_id=self.agent_id,
                display_name=self.agent_id,
                status=DetectionStatus.INSTALLED,
                installed=True,
                version=f"1.0.{self.calls}",
                executable_path_internal=f"C:/{self.agent_id}.exe",
                detection_source=DetectionSource.PATH,
                probe_status=ProbeStatus.HEALTHY,
                observed_at=datetime.now(UTC),
                user_message="ok",
                official_install_url="https://example.invalid/install",
                revision="sha256:" + str(self.calls) * 64,
            )

    detectors = {slot: Detector(slot) for slot in ("hermes", "claude", "codex")}
    service = AgentDetectionService(
        detectors,  # type: ignore[arg-type]
        ttl_seconds=30,
        monotonic=lambda: now[0],
    )
    assert service.get("claude").version == "1.0.1"
    assert service.get("claude").version == "1.0.1"
    assert service.get("claude", refresh=True).version == "1.0.2"
    now[0] = 31
    assert service.get("claude").version == "1.0.3"


def test_public_snapshot_never_exposes_executable_path():
    result = AgentDetectionResult(
        agent_id="codex",
        display_name="Codex",
        status=DetectionStatus.INSTALLED,
        installed=True,
        version="1.2.3",
        executable_path_internal="C:/Users/private/秘密/codex.exe",
        detection_source=DetectionSource.PATH,
        probe_status=ProbeStatus.HEALTHY,
        observed_at=datetime.now(UTC),
        user_message="ok",
        official_install_url="https://example.invalid/install",
        revision="sha256:" + "a" * 64,
    )
    serialized = result.public_snapshot().model_dump_json()
    assert "executable" not in serialized
    assert "private" not in serialized
