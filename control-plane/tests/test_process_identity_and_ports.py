from __future__ import annotations

import os
import socket
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from control_plane.installer.artifacts import InstallerError, sha256_file
from control_plane.lifecycle.port_ownership import PortOwnershipInspector
from control_plane.lifecycle.process_identity import ProcessIdentityInspector


class ObservedProcess:
    def __init__(self, executable: Path, arguments: list[str]) -> None:
        self.executable = executable
        self.arguments = arguments
        self.created = time.time() - 2
        self.parent = os.getpid()

    def exe(self):
        return str(self.executable)

    def create_time(self):
        return self.created

    def ppid(self):
        return self.parent

    def cmdline(self):
        return self.arguments


def test_process_identity_binds_full_command_and_detects_pid_reuse_and_sha_change(tmp_path):
    executable = tmp_path / "cc-connect.exe"
    executable.write_bytes(b"managed executable bytes")
    config = tmp_path / "配置 路径 (managed).toml"
    config.write_text("schema_version='1.0'\n", encoding="utf-8")
    arguments = [str(executable), "-config", str(config)]
    process = ObservedProcess(executable, arguments)
    inspector = ProcessIdentityInspector(lambda _pid: process)
    identity = inspector.capture(
        pid=4242,
        expected_executable=executable,
        expected_sha256=sha256_file(executable),
        expected_arguments=arguments,
        component_id="cc-connect",
        product_instance_id="instance-" + "a" * 24,
        artifact_id="artifact-1",
        configuration_revision=3,
        listen_host="127.0.0.1",
        listen_port=59030,
        operation_id="op-start",
    )
    assert inspector.verify(identity).status == "verified"

    process.created += 100
    reused = inspector.verify(identity)
    assert reused.status == "pid_reused"
    assert reused.diagnostic_code == "MANAGED_PROCESS_PID_REUSED"

    process.created -= 100
    executable.write_bytes(b"tampered executable bytes")
    mismatch = inspector.verify(identity)
    assert mismatch.status == "mismatch"
    assert mismatch.diagnostic_code == "MANAGED_PROCESS_EXECUTABLE_INTEGRITY_FAILURE"


def test_capture_rejects_command_or_executable_mismatch(tmp_path):
    executable = tmp_path / "cc-connect.exe"
    executable.write_bytes(b"managed executable")
    config = tmp_path / "managed.toml"
    config.write_text("", encoding="utf-8")
    process = ObservedProcess(executable, [str(executable), "-config", str(config), "unexpected"])
    inspector = ProcessIdentityInspector(lambda _pid: process)
    with pytest.raises(InstallerError) as captured:
        inspector.capture(
            pid=4243,
            expected_executable=executable,
            expected_sha256=sha256_file(executable),
            expected_arguments=[str(executable), "-config", str(config)],
            component_id="cc-connect",
            product_instance_id="instance-" + "b" * 24,
            artifact_id="artifact-1",
            configuration_revision=1,
            listen_host="127.0.0.1",
            listen_port=59031,
            operation_id="op-start",
        )
    assert captured.value.code == "MANAGED_PROCESS_IDENTITY_MISMATCH"


def test_port_owner_mapping_requires_exact_pid_and_never_claims_ipv6_support():
    connections = [
        SimpleNamespace(status="LISTEN", laddr=("127.0.0.1", 59032), pid=5001),
    ]
    inspector = PortOwnershipInspector(connections_provider=lambda: connections)
    owned = inspector.inspect("127.0.0.1", 59032, expected_pid=5001)
    assert owned.status == "owned"
    assert owned.owner_pid == 5001
    assert owned.ipv6_status == "unknown"
    conflict = inspector.inspect("127.0.0.1", 59032, expected_pid=5002)
    assert conflict.status == "conflict"
    assert conflict.owner_pid == 5001


def test_real_loopback_bind_probe_and_non_loopback_rejection():
    inspector = PortOwnershipInspector(connections_provider=lambda: [])
    port = inspector.choose_available()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
    if exclusive is not None:
        listener.setsockopt(socket.SOL_SOCKET, exclusive, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen(1)
    try:
        assert inspector.is_available("127.0.0.1", port) is False
    finally:
        listener.close()
    with pytest.raises(InstallerError) as captured:
        inspector.is_available("0.0.0.0", 59033)
    assert captured.value.code == "NON_LOOPBACK_LISTEN_FORBIDDEN"
